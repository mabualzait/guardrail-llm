from __future__ import annotations

import json
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, Union
from guardrail.config import SchemaConfig
from guardrail.schema.repair import parse_or_repair_json, repair_json
from guardrail.schema.validator import validate_json_schema, ValidationError


class SchemaViolationError(Exception):
    def __init__(self, message: str, errors: List[str], raw_content: str) -> None:
        super().__init__(message)
        self.errors = errors
        self.raw_content = raw_content

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "message": str(self),
                "type": "schema_validation_error",
                "code": "schema_validation_failed",
                "details": self.errors,
                "raw_content": self.raw_content,
            }
        }


class SchemaEnforcer:
    """Enforces valid JSON and structural schema adherence with auto-healing and retry capabilities."""

    def __init__(self, config: Optional[SchemaConfig] = None) -> None:
        self.config = config or SchemaConfig()

    @property
    def is_active(self) -> bool:
        return self.config.enabled or self.config.strict_json or bool(self.config.schema_definition)

    def enforce_sync(self, content: str) -> Tuple[str, bool]:
        """Synchronously parses, repairs, and validates JSON content.

        Returns:
            Tuple of (formatted_json_string, was_repaired).
        Raises:
            SchemaViolationError if invalid and repair fails.
        """
        if not self.is_active:
            return content, False

        # 1. Attempt parsing / repair
        try:
            parsed, was_repaired = parse_or_repair_json(content)
        except Exception as e:
            raise SchemaViolationError(
                f"Failed to parse or repair JSON: {e}",
                errors=[str(e)],
                raw_content=content,
            )

        # 2. Schema validation if schema is provided
        if self.config.schema_definition:
            errors = validate_json_schema(parsed, self.config.schema_definition)
            if errors:
                raise SchemaViolationError(
                    "JSON does not conform to the required schema",
                    errors=errors,
                    raw_content=content,
                )

        return json.dumps(parsed, ensure_ascii=False), was_repaired

    async def enforce_async(
        self,
        content: str,
        repair_callback: Optional[Callable[[str, List[str]], Coroutine[Any, Any, str]]] = None,
    ) -> Tuple[str, bool]:
        """Asynchronously parses, repairs, and optionally executes a 1-shot retry loop via upstream."""
        if not self.is_active:
            return content, False

        try:
            return self.enforce_sync(content)
        except SchemaViolationError as err:
            # Check if 1-shot repair retry is enabled
            if self.config.on_failure == "retry" and self.config.max_repair_retries > 0 and repair_callback:
                # Execute 1-shot self-repair call to upstream
                try:
                    fixed_content = await repair_callback(content, err.errors)
                    # Attempt parse/validation again on the repaired completion
                    parsed, _ = parse_or_repair_json(fixed_content)
                    if self.config.schema_definition:
                        retry_errors = validate_json_schema(parsed, self.config.schema_definition)
                        if retry_errors:
                            raise SchemaViolationError(
                                "Schema validation failed after upstream repair retry",
                                errors=retry_errors,
                                raw_content=fixed_content,
                            )
                    return json.dumps(parsed, ensure_ascii=False), True
                except Exception as retry_err:
                    if isinstance(retry_err, SchemaViolationError):
                        raise retry_err
                    raise SchemaViolationError(
                        f"Upstream repair retry failed: {retry_err}",
                        errors=err.errors + [str(retry_err)],
                        raw_content=content,
                    )
            raise err
