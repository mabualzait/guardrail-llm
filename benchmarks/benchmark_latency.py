#!/usr/bin/env python3
"""benchmarks/benchmark_latency.py: Micro-benchmark comparing raw upstream vs. proxied guardrail pipeline."""

from __future__ import annotations

import asyncio
import statistics
import time
from guardrail.chain import GuardrailChain
from guardrail.config import GuardrailConfig


async def run_benchmark(num_requests: int = 1000):
    print("=" * 70)
    print("           GUARDRAIL-LLM LATENCY & OVERHEAD BENCHMARK")
    print("=" * 70)
    print(f"Executing {num_requests} requests through pipeline with:")
    print(" - Linear-time PII regex scanning & reversible masking")
    print(" - JSON extraction from markdown code fences")
    print(" - Deterministic malformed JSON auto-repair (trailing commas, quotes)")
    print(" - JSON Schema validation")
    print(" - Sliding window token budgeting & rate limit check")
    print("=" * 70)

    cfg = GuardrailConfig()
    cfg.pii.enabled = True
    cfg.pii.reversible = True
    cfg.schema_rule.enabled = True
    cfg.schema_rule.strict_json = True
    cfg.schema_rule.schema_definition = {
        "type": "object",
        "required": ["status", "target", "count"],
        "properties": {
            "status": {"type": "string"},
            "target": {"type": "string"},
            "count": {"type": "integer"},
        },
    }
    cfg.budget.enabled = True
    cfg.budget.max_requests_per_minute = 1000000
    cfg.budget.max_tokens_per_minute = 100000000

    chain = GuardrailChain(cfg)

    payload = {
        "model": "llama3",
        "messages": [
            {
                "role": "user",
                "content": "Alert user at dev-ops@company.org regarding server incident 192.168.1.1!",
            }
        ],
    }

    mock_llm_response = {
        "id": "chatcmpl-bench-001",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "llama3",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '```json\n{"status": "dispatched", "target": "[EMAIL_1]", "count": 1,}\n```',
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35},
    }

    # Warmup
    for _ in range(50):
        s_payload, ctx = chain.prepare_inbound(payload, "warmup")
        _ = await chain.process_outbound(mock_llm_response, ctx)

    # Benchmark loop
    pipeline_latencies = []
    t_start_total = time.perf_counter()

    for i in range(num_requests):
        t0 = time.perf_counter()
        s_payload, ctx = chain.prepare_inbound(payload, f"client_{i}")
        res = await chain.process_outbound(mock_llm_response, ctx)
        t1 = time.perf_counter()
        pipeline_latencies.append((t1 - t0) * 1000.0)

    t_total_elapsed = time.perf_counter() - t_start_total

    # Compute statistics
    sorted_lat = sorted(pipeline_latencies)
    mean_lat = statistics.mean(pipeline_latencies)
    median_lat = statistics.median(pipeline_latencies)
    p95_lat = sorted_lat[int(len(sorted_lat) * 0.95)]
    p99_lat = sorted_lat[int(len(sorted_lat) * 0.99)]
    max_lat = max(sorted_lat)
    min_lat = min(sorted_lat)
    throughput = num_requests / t_total_elapsed

    print("\nRESULTS SUMMARY:")
    print("-" * 70)
    print(f"  Total Requests:         {num_requests}")
    print(f"  Total Wall Clock Time:  {t_total_elapsed:.3f} s")
    print(f"  Pipeline Throughput:    {throughput:.1f} req/s")
    print("-" * 70)
    print(f"  Min Added Overhead:     {min_lat:.3f} ms")
    print(f"  Mean Added Overhead:    {mean_lat:.3f} ms")
    print(f"  Median (P50) Overhead:  {median_lat:.3f} ms")
    print(f"  P95 Overhead:           {p95_lat:.3f} ms")
    print(f"  P99 Overhead:           {p99_lat:.3f} ms")
    print(f"  Max Overhead:           {max_lat:.3f} ms")
    print("-" * 70)

    target_met = mean_lat < 5.0
    status_str = "PASSED (< 5ms target)" if target_met else "FAILED (>= 5ms target)"
    print(f"  ACCEPTANCE CRITERION:   {status_str}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_benchmark(1000))
