from __future__ import annotations

import json
import pytest
from guardrail.config import SchemaConfig
from guardrail.schema.enforcer import SchemaEnforcer, SchemaViolationError
from guardrail.schema.repair import extract_json_block, parse_or_repair_json, repair_json
from guardrail.schema.validator import validate_json_schema


def test_extract_json_block():
    text_with_fences = "Here is the result:\n```json\n{\n  \"name\": \"Antigravity\"\n}\n```\nHope that helps!"
    extracted = extract_json_block(text_with_fences)
    assert extracted == '{\n  "name": "Antigravity"\n}'

    text_conversational = "Sure, I have prepared the data: {\"status\": \"ok\", \"code\": 200}. Let me know if you need more."
    extracted_conv = extract_json_block(text_conversational)
    assert extracted_conv == '{"status": "ok", "code": 200}'


def test_repair_json_dirty_elements():
    # Dirty JSON with single quotes, trailing commas, Python literals, comments, unclosed braces
    dirty = """
    // Leading comments
    {
      'name': 'Project Alpha',
      'active': True,
      'tags': ['llm', 'guardrail',], /* inline comment */
      'budget': None,
      'metadata': {
        'version': 1.0,
    """
    repaired = repair_json(dirty)
    parsed = json.loads(repaired)

    assert parsed["name"] == "Project Alpha"
    assert parsed["active"] is True
    assert parsed["tags"] == ["llm", "guardrail"]
    assert parsed["budget"] is None
    assert parsed["metadata"]["version"] == 1.0


def test_parse_or_repair_json_fast_path():
    valid = '{"key": "value", "count": 42}'
    data, repaired = parse_or_repair_json(valid)
    assert data == {"key": "value", "count": 42}
    assert repaired is False


def test_json_schema_validator():
    schema = {
        "type": "object",
        "required": ["username", "age", "roles"],
        "properties": {
            "username": {"type": "string", "minLength": 3},
            "age": {"type": "integer", "minimum": 18},
            "status": {"type": "string", "enum": ["active", "pending", "banned"]},
            "roles": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
        },
    }

    # Valid data
    valid_data = {
        "username": "alice",
        "age": 25,
        "status": "active",
        "roles": ["admin"],
    }
    assert validate_json_schema(valid_data, schema) == []

    # Invalid data
    invalid_data = {
        "username": "al",  # too short
        "age": "twenty-five",  # wrong type
        "status": "unknown",  # invalid enum
        "roles": [],  # too few items
        # required fields missing: None missing here except type mismatch
    }
    errors = validate_json_schema(invalid_data, schema)
    assert len(errors) >= 4
    assert any("minLength" in e for e in errors)
    assert any("expected type 'integer'" in e for e in errors)
    assert any("allowed enum" in e for e in errors)
    assert any("minItems" in e for e in errors)


@pytest.mark.asyncio
async def test_schema_enforcer_success():
    schema = {
        "type": "object",
        "required": ["id", "result"],
        "properties": {
            "id": {"type": "integer"},
            "result": {"type": "string"},
        },
    }
    config = SchemaConfig(enabled=True, schema=schema, repair_malformed=True)
    enforcer = SchemaEnforcer(config)

    content = "```json\n{'id': 101, 'result': 'success',}\n```"
    fixed_json_str, repaired = await enforcer.enforce_async(content)
    assert repaired is True
    data = json.loads(fixed_json_str)
    assert data == {"id": 101, "result": "success"}


@pytest.mark.asyncio
async def test_schema_enforcer_one_shot_retry_loop():
    schema = {
        "type": "object",
        "required": ["score"],
        "properties": {"score": {"type": "integer"}},
    }
    config = SchemaConfig(
        enabled=True,
        schema=schema,
        on_failure="retry",
        max_repair_retries=1,
    )
    enforcer = SchemaEnforcer(config)

    broken_content = '{"score": "not_an_int"}'

    # Mock upstream repair callback
    async def mock_repair(faulty_content: str, errors: list[str]) -> str:
        assert "expected type 'integer'" in errors[0]
        return '{"score": 95}'

    fixed_json_str, repaired = await enforcer.enforce_async(
        broken_content, repair_callback=mock_repair
    )
    assert repaired is True
    assert json.loads(fixed_json_str) == {"score": 95}


@pytest.mark.asyncio
async def test_schema_enforcer_fatal_failure():
    schema = {
        "type": "object",
        "required": ["id"],
    }
    config = SchemaConfig(enabled=True, schema=schema, on_failure="error")
    enforcer = SchemaEnforcer(config)

    with pytest.raises(SchemaViolationError) as exc_info:
        await enforcer.enforce_async("This is completely non-json content.")

    assert "Failed to parse" in str(exc_info.value)
    error_dict = exc_info.value.to_dict()
    assert error_dict["error"]["code"] == "schema_validation_failed"


def test_schema_validator_comprehensive_types():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "flag": {"type": "boolean"},
            "rating": {"type": "number", "minimum": 1.0, "maximum": 5.0},
            "code": {"type": "string", "pattern": r"^CODE-\d+$"},
            "optional_data": {"type": "null"},
            "items": {"type": "array", "minItems": 2, "maxItems": 3},
        },
    }

    valid_payload = {
        "flag": True,
        "rating": 4.5,
        "code": "CODE-1234",
        "optional_data": None,
        "items": ["a", "b"],
    }
    assert validate_json_schema(valid_payload, schema) == []

    invalid_payload = {
        "flag": "not_a_bool",
        "rating": 6.5,
        "code": "INVALID_CODE",
        "optional_data": "not_null",
        "items": ["a"],
        "extra_key": "not allowed",
    }
    errors = validate_json_schema(invalid_payload, schema)
    assert len(errors) == 6
    assert any("expected type 'boolean'" in e for e in errors)
    assert any("greater than maximum" in e for e in errors)
    assert any("does not match required regex" in e for e in errors)
    assert any("expected type 'null'" in e for e in errors)
    assert any("less than minItems" in e for e in errors)
    assert any("additional property is not allowed" in e for e in errors)


def test_repair_json_edge_cases():
    # Empty string raises
    with pytest.raises(ValueError):
        parse_or_repair_json("   ")

    # Comment syntax inside quotes should not be stripped
    url_json = '{"url": "http://example.com/*test*/page//1"}'
    repaired_url = repair_json(url_json)
    assert json.loads(repaired_url)["url"] == "http://example.com/*test*/page//1"

    # Unclosed string at the end
    unclosed_str = '{"message": "Hello world'
    repaired_str = repair_json(unclosed_str)
    assert json.loads(repaired_str)["message"] == "Hello world"

