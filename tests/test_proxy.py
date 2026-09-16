from __future__ import annotations

import json
import pytest
import httpx
from guardrail.config import GuardrailConfig
from guardrail.proxy.app import create_app


def create_mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_health_and_metrics_endpoints():
    cfg = GuardrailConfig()
    app = create_app(cfg)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["service"] == "guardrail-llm"

        res_metrics = await client.get("/metrics")
        assert res_metrics.status_code == 200
        metrics = res_metrics.json()
        assert "requests" in metrics
        assert "guardrails" in metrics
        assert "latency_ms" in metrics


@pytest.mark.asyncio
async def test_chat_completions_proxy_pii_roundtrip():
    captured_upstream_request = {}

    def mock_upstream(request: httpx.Request) -> httpx.Response:
        captured_upstream_request["body"] = json.loads(request.read())
        # Upstream echoes back the masked entity
        response_body = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "llama3",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "I will send confirmation to [EMAIL_1].",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25},
        }
        return httpx.Response(200, json=response_body)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))

    cfg = GuardrailConfig()
    cfg.pii.enabled = True
    cfg.pii.reversible = True

    app = create_app(config=cfg, upstream_client=mock_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        req_payload = {
            "model": "llama3",
            "messages": [
                {"role": "user", "content": "My contact is test@example.com."}
            ],
        }
        res = await client.post("/v1/chat/completions", json=req_payload)
        assert res.status_code == 200
        res_data = res.json()

        # Check that upstream got the SANITIZED prompt
        upstream_user_msg = captured_upstream_request["body"]["messages"][0]["content"]
        assert "test@example.com" not in upstream_user_msg
        assert "[EMAIL_1]" in upstream_user_msg

        # Check that client got REVERSED original email in assistant reply
        reply = res_data["choices"][0]["message"]["content"]
        assert "[EMAIL_1]" not in reply
        assert "I will send confirmation to test@example.com." == reply


@pytest.mark.asyncio
async def test_chat_completions_schema_repair():
    def mock_upstream(request: httpx.Request) -> httpx.Response:
        # Upstream returns markdown wrapped JSON with trailing comma
        response_body = {
            "id": "chatcmpl-456",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "llama3",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Sure, here is your JSON:\n```json\n{'answer': 42, 'status': 'ok',}\n```",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
        }
        return httpx.Response(200, json=response_body)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))

    cfg = GuardrailConfig()
    cfg.schema_rule.enabled = True
    cfg.schema_rule.strict_json = True
    cfg.schema_rule.repair_malformed = True

    app = create_app(config=cfg, upstream_client=mock_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "Return json"}]},
        )
        assert res.status_code == 200
        content = res.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        assert parsed == {"answer": 42, "status": "ok"}


@pytest.mark.asyncio
async def test_chat_completions_streaming_sse():
    def mock_upstream(request: httpx.Request) -> httpx.Response:
        lines = [
            'data: {"id":"1","choices":[{"delta":{"content":"Hello "}}]}\n\n',
            'data: {"id":"2","choices":[{"delta":{"content":"world!"}}]}\n\n',
            "data: [DONE]\n\n",
        ]
        return httpx.Response(
            200,
            content="".join(lines).encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))

    cfg = GuardrailConfig()
    app = create_app(config=cfg, upstream_client=mock_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
        )
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        body = res.text
        assert "Hello " in body
        assert "world!" in body
        assert "data: [DONE]" in body


@pytest.mark.asyncio
async def test_legacy_completions_endpoint():
    def mock_upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "cmpl-1",
                "object": "text_completion",
                "choices": [{"text": "Hello user!", "index": 0}],
                "usage": {"total_tokens": 5},
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))
    cfg = GuardrailConfig()
    app = create_app(config=cfg, upstream_client=mock_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/v1/completions", json={"model": "gpt-3.5-turbo-instruct", "prompt": "Hi"})
        assert res.status_code == 200
        assert res.json()["choices"][0]["text"] == "Hello user!"


@pytest.mark.asyncio
async def test_upstream_connection_failure():
    def mock_upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by upstream", request=request)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))
    cfg = GuardrailConfig()
    app = create_app(config=cfg, upstream_client=mock_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "Hi"}]},
        )
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "upstream_connection_failed"


def test_extract_client_id_variants():
    from guardrail.proxy.app import extract_client_id

    assert extract_client_id(x_client_id="custom_tenant") == "custom_tenant"
    assert extract_client_id(authorization="Bearer secret_token") == "secret_token"
    assert extract_client_id(client_host="192.168.1.5") == "192.168.1.5"
    assert extract_client_id() == "anonymous_client"


@pytest.mark.asyncio
async def test_budget_exceeded_proxy_rejections():
    def mock_upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))
    cfg = GuardrailConfig()
    cfg.budget.enabled = True
    cfg.budget.max_requests_per_minute = 1

    app = create_app(config=cfg, upstream_client=mock_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Request 1: succeeds
        res1 = await client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "One"}]},
            headers={"X-Client-ID": "tenant_1"},
        )
        assert res1.status_code == 200

        # Request 2: blocked with 429
        res2 = await client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "Two"}]},
            headers={"X-Client-ID": "tenant_1"},
        )
        assert res2.status_code == 429
        assert res2.json()["error"]["code"] == "token_budget_exceeded"


@pytest.mark.asyncio
async def test_schema_violation_proxy_http_400():
    def mock_upstream(request: httpx.Request) -> httpx.Response:
        # Returns unfixable garbage
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Not JSON at all",
                        }
                    }
                ]
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))
    cfg = GuardrailConfig()
    cfg.schema_rule.enabled = True
    cfg.schema_rule.strict_json = True
    cfg.schema_rule.on_failure = "error"

    app = create_app(config=cfg, upstream_client=mock_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "Return json"}]},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "schema_validation_failed"


@pytest.mark.asyncio
async def test_streaming_legacy_completions():
    def mock_upstream(request: httpx.Request) -> httpx.Response:
        lines = [
            'data: {"id":"1","choices":[{"text":"Streamed "}]}\n\n',
            'data: {"id":"2","choices":[{"text":"completion"}]}\n\n',
            "data: [DONE]\n\n",
        ]
        return httpx.Response(
            200,
            content="".join(lines).encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))
    cfg = GuardrailConfig()
    app = create_app(config=cfg, upstream_client=mock_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/completions",
            json={"model": "gpt-3.5-turbo-instruct", "prompt": "Hi", "stream": True},
        )
        assert res.status_code == 200
        assert "Streamed " in res.text
        assert "completion" in res.text
        assert "data: [DONE]" in res.text


@pytest.mark.asyncio
async def test_upstream_http_status_error_forwarding():
    def mock_upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Invalid API Key", "type": "invalid_request_error"}},
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_upstream))
    cfg = GuardrailConfig()
    app = create_app(config=cfg, upstream_client=mock_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "Hi"}]},
        )
        assert res.status_code == 401
        assert res.json()["error"]["message"] == "Invalid API Key"

