from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator
import yaml


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 1
    timeout: float = 60.0


class UpstreamConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    timeout: float = 60.0
    headers: Dict[str, str] = Field(default_factory=dict)


class PIICustomPattern(BaseModel):
    pattern: str
    placeholder: Optional[str] = None


class PIIConfig(BaseModel):
    enabled: bool = True
    patterns: List[str] = Field(
        default_factory=lambda: [
            "email",
            "phone",
            "credit_card",
            "ipv4",
            "ssn",
            "api_key",
        ]
    )
    custom_patterns: Dict[str, Union[str, PIICustomPattern]] = Field(default_factory=dict)
    reversible: bool = True


from pydantic import BaseModel, ConfigDict, Field


class SchemaConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool = False
    strict_json: bool = False
    repair_malformed: bool = True
    max_repair_retries: int = 1
    on_failure: Literal["retry", "error"] = "retry"
    schema_definition: Optional[Dict[str, Any]] = Field(default=None, alias="schema")


class BudgetConfig(BaseModel):
    enabled: bool = True
    max_tokens_per_request: int = 4096
    max_requests_per_minute: int = 60
    max_tokens_per_minute: int = 100000
    sliding_window_seconds: int = 60
    reject_status_code: int = 429


class MetricsConfig(BaseModel):
    enabled: bool = True


class GuardrailConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server: ServerConfig = Field(default_factory=ServerConfig)
    upstream: UpstreamConfig = Field(default_factory=UpstreamConfig)
    pii: PIIConfig = Field(default_factory=PIIConfig)
    schema_rule: SchemaConfig = Field(default_factory=SchemaConfig, alias="schema")
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GuardrailConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, file_path: Union[str, Path]) -> GuardrailConfig:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")
        with open(path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}

        # Environment variable overrides
        if "UPSTREAM_BASE_URL" in os.environ:
            raw_data.setdefault("upstream", {})["base_url"] = os.environ["UPSTREAM_BASE_URL"]
        if "GUARDRAIL_PORT" in os.environ:
            raw_data.setdefault("server", {})["port"] = int(os.environ["GUARDRAIL_PORT"])
        if "GUARDRAIL_HOST" in os.environ:
            raw_data.setdefault("server", {})["host"] = os.environ["GUARDRAIL_HOST"]

        return cls.model_validate(raw_data)


def load_config(source: Optional[Union[str, Path, Dict[str, Any], GuardrailConfig]] = None) -> GuardrailConfig:
    if source is None:
        default_yaml = Path("guardrail.yaml")
        if default_yaml.exists():
            return GuardrailConfig.from_yaml(default_yaml)
        return GuardrailConfig()

    if isinstance(source, GuardrailConfig):
        return source
    if isinstance(source, dict):
        return GuardrailConfig.from_dict(source)
    if isinstance(source, (str, Path)):
        return GuardrailConfig.from_yaml(source)

    raise TypeError(f"Invalid configuration source type: {type(source)}")
