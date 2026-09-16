from __future__ import annotations

import os
from pathlib import Path
import pytest
from guardrail.config import GuardrailConfig, PIICustomPattern, load_config


def test_default_config():
    cfg = GuardrailConfig()
    assert cfg.server.port == 8080
    assert cfg.upstream.base_url == "http://localhost:11434/v1"
    assert cfg.pii.enabled is True
    assert "email" in cfg.pii.patterns
    assert cfg.budget.enabled is True
    assert cfg.schema_rule.repair_malformed is True


def test_config_from_dict():
    data = {
        "server": {"port": 9000, "host": "127.0.0.1"},
        "upstream": {"base_url": "http://localhost:8000/v1"},
        "pii": {
            "enabled": True,
            "patterns": ["email"],
            "custom_patterns": {
                "passport": r"\b[A-Z]{1,2}\d{7,8}\b",
                "employee_id": {"pattern": r"\bEMP-\d{4}\b", "placeholder": "[STAFF_{idx}]"},
            },
            "reversible": False,
        },
        "schema": {
            "strict_json": True,
            "on_failure": "error",
            "schema": {"type": "object", "required": ["name"]},
        },
        "budget": {
            "max_tokens_per_request": 2048,
            "max_requests_per_minute": 30,
            "reject_status_code": 402,
        },
    }
    cfg = GuardrailConfig.from_dict(data)
    assert cfg.server.port == 9000
    assert cfg.upstream.base_url == "http://localhost:8000/v1"
    assert cfg.pii.patterns == ["email"]
    assert "passport" in cfg.pii.custom_patterns
    assert cfg.pii.reversible is False
    assert cfg.schema_rule.strict_json is True
    assert cfg.budget.reject_status_code == 402


def test_config_from_yaml(tmp_path: Path, monkeypatch):
    yaml_file = tmp_path / "test_config.yaml"
    yaml_file.write_text(
        """
server:
  port: 8888
upstream:
  base_url: "http://ollama:11434/v1"
pii:
  enabled: false
"""
    )
    cfg = load_config(yaml_file)
    assert cfg.server.port == 8888
    assert cfg.upstream.base_url == "http://ollama:11434/v1"
    assert cfg.pii.enabled is False

    # Test environment variable override
    monkeypatch.setenv("GUARDRAIL_PORT", "9999")
    monkeypatch.setenv("UPSTREAM_BASE_URL", "http://vllm:8000/v1")
    cfg_env = load_config(yaml_file)
    assert cfg_env.server.port == 9999
    assert cfg_env.upstream.base_url == "http://vllm:8000/v1"


def test_invalid_config_path():
    with pytest.raises(FileNotFoundError):
        load_config("/non/existent/path/to/config.yaml")

    with pytest.raises(TypeError):
        load_config(12345)  # type: ignore
