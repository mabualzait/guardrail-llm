from __future__ import annotations

import json
import pytest
import httpx
from guardrail.sdk.client import GuardrailedClient


def make_mock_client():
    def handler(request: httpx.Request) -> httpx.Response:
        req_json = json.loads(request.read())
        messages = req_json.get("messages", [])
        user_content = messages[0]["content"] if messages else ""

        # Upstream responds with a greeting containing whatever placeholder was sent
        reply = f"Echoing back: {user_content}"
        return httpx.Response(
            200,
            json={
                "id": "sdk-chatcmpl",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_sdk_async_chat_completion():
    mock_httpx = make_mock_client()
    client = GuardrailedClient(
        upstream_url="http://mock-upstream/v1",
        pii=True,
        httpx_client=mock_httpx,
    )

    res = await client.chat.completions.acreate(
        model="llama3",
        messages=[{"role": "user", "content": "My email is agent@deepmind.com"}],
    )

    assert res["id"] == "sdk-chatcmpl"
    content = res["choices"][0]["message"]["content"]
    # Verify reversible PII works: the placeholder is de-anonymized back to original email
    assert "agent@deepmind.com" in content
    assert client.chain.limiter.get_stats("sdk_client")["lifetime_tokens"] == 18

    await client.aclose()


def test_sdk_sync_chat_completion():
    mock_httpx = make_mock_client()
    with GuardrailedClient(
        upstream_url="http://mock-upstream/v1",
        pii=True,
        httpx_client=mock_httpx,
    ) as client:
        res = client.chat.completions.create(
            model="llama3",
            messages=[{"role": "user", "content": "Call me at 800-555-0199"}],
        )
        assert res["id"] == "sdk-chatcmpl"
        content = res["choices"][0]["message"]["content"]
        assert "800-555-0199" in content


def test_sdk_legacy_completions():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "sdk-cmpl",
                "object": "text_completion",
                "choices": [{"text": "Completion response", "index": 0}],
                "usage": {"total_tokens": 12},
            },
        )

    mock_httpx = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GuardrailedClient(upstream_url="http://mock/v1", httpx_client=mock_httpx)
    res = client.completions.create(model="davinci", prompt="Hello")
    assert res["choices"][0]["text"] == "Completion response"
    client.close()
