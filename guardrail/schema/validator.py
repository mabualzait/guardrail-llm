from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


class ValidationError(Exception):
    def __init__(self, message: str, errors: List[str]) -> None:
        super().__init__(message)
        self.errors = errors


def validate_json_schema(data: Any, schema: Dict[str, Any], path: str = "root") -> List[str]:
    """Lightweight, recursive JSON Schema validator with zero external dependencies.

    Returns a list of error strings (empty if valid).
    """
    errors: List[str] = []

    # 1. Type validation
    expected_type = schema.get("type")
    if expected_type:
        type_valid = False
        types = [expected_type] if isinstance(expected_type, str) else expected_type

        for t in types:
            if t == "null" and data is None:
                type_valid = True
                break
            elif t == "boolean" and isinstance(data, bool):
                type_valid = True
                break
            elif t == "integer" and isinstance(data, int) and not isinstance(data, bool):
                type_valid = True
                break
            elif t == "number" and (isinstance(data, (int, float)) and not isinstance(data, bool)):
                type_valid = True
                break
            elif t == "string" and isinstance(data, str):
                type_valid = True
                break
            elif t == "array" and isinstance(data, list):
                type_valid = True
                break
            elif t == "object" and isinstance(data, dict):
                type_valid = True
                break

        if not type_valid:
            actual_type = type(data).__name__ if data is not None else "null"
            if isinstance(data, bool):
                actual_type = "boolean"
            errors.append(f"{path}: expected type '{expected_type}', got '{actual_type}'")
            return errors

    # If data is None and null was allowed, return
    if data is None:
        return errors

    # 2. Enum check
    if "enum" in schema:
        if data not in schema["enum"]:
            errors.append(f"{path}: value {repr(data)} is not in allowed enum {schema['enum']}")

    # 3. String constraints
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append(f"{path}: string length {len(data)} is less than minLength {schema['minLength']}")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append(f"{path}: string length {len(data)} exceeds maxLength {schema['maxLength']}")
        if "pattern" in schema:
            if not re.search(schema["pattern"], data):
                errors.append(f"{path}: string does not match required regex pattern '{schema['pattern']}'")

    # 4. Number constraints
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: number {data} is less than minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{path}: number {data} is greater than maximum {schema['maximum']}")

    # 5. Object validation
    if isinstance(data, dict):
        required_fields = schema.get("required", [])
        for field in required_fields:
            if field not in data:
                errors.append(f"{path}.{field}: required field is missing")

        properties = schema.get("properties", {})
        for key, val in data.items():
            if key in properties:
                sub_errors = validate_json_schema(val, properties[key], path=f"{path}.{key}")
                errors.extend(sub_errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: additional property is not allowed")

    # 6. Array validation
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append(f"{path}: array length {len(data)} is less than minItems {schema['minItems']}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append(f"{path}: array length {len(data)} exceeds maxItems {schema['maxItems']}")

        items_schema = schema.get("items")
        if items_schema and isinstance(items_schema, dict):
            for idx, item in enumerate(data):
                sub_errors = validate_json_schema(item, items_schema, path=f"{path}[{idx}]")
                errors.extend(sub_errors)

    return errors
