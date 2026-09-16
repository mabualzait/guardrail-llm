from __future__ import annotations

import time
import pytest
from guardrail.chain import GuardrailChain
from guardrail.config import GuardrailConfig


@pytest.mark.asyncio
async def test_guardrail_latency_overhead_under_5ms():
    """Verifies that guardrail pipeline adds < 5ms latency overhead per request."""
    cfg = GuardrailConfig()
    cfg.pii.enabled = True
    cfg.pii.reversible = True
    cfg.schema_rule.enabled = True
    cfg.schema_rule.strict_json = True
    cfg.budget.enabled = True

    chain = GuardrailChain(cfg)

    payload = {
        "model": "llama3",
        "messages": [
            {
                "role": "user",
                "content": "Please send user report to support@mycorp.com and call 555-123-4567.",
            }
        ],
    }

    mock_response = {
        "id": "chatcmpl-bench",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '```json\n{"status": "dispatched", "target": "[EMAIL_1]", "phone": "[PHONE_1]",}\n```',
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 25, "completion_tokens": 20, "total_tokens": 45},
    }

    # Warmup
    for _ in range(10):
        s_payload, ctx = chain.prepare_inbound(payload, "bench_user")
        _ = await chain.process_outbound(mock_response, ctx)

    durations = []
    iterations = 200

    for i in range(iterations):
        t0 = time.perf_counter()
        s_payload, ctx = chain.prepare_inbound(payload, f"bench_user_{i}")
        processed = await chain.process_outbound(mock_response, ctx)
        t1 = time.perf_counter()
        durations.append((t1 - t0) * 1000.0)  # ms

    avg_overhead_ms = sum(durations) / len(durations)
    p95_overhead_ms = sorted(durations)[int(len(durations) * 0.95)]

    print(f"\n[LATENCY BENCHMARK] Average overhead: {avg_overhead_ms:.3f} ms | P95: {p95_overhead_ms:.3f} ms")

    # Hard acceptance assertion: Added latency must be < 5.0 ms
    assert avg_overhead_ms < 5.0, f"Average overhead {avg_overhead_ms}ms exceeded 5ms limit!"
    assert p95_overhead_ms < 10.0, f"P95 overhead {p95_overhead_ms}ms was unexpectedly high!"
