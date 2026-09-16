from __future__ import annotations

from guardrail.proxy.metrics import MetricsCollector


def test_metrics_collector():
    metrics = MetricsCollector()
    metrics.record_request_start()
    metrics.record_success(duration_ms=2.5, prompt_tokens=10, completion_tokens=20)
    metrics.record_rate_limit_block()
    metrics.record_schema_violation()
    metrics.record_schema_repair()
    metrics.record_pii_detections({"email": 2, "phone": 1})

    summary = metrics.get_summary()
    assert summary["requests"]["total"] == 1
    assert summary["requests"]["successful"] == 1
    assert summary["requests"]["blocked_rate_limit"] == 1
    assert summary["guardrails"]["pii_redactions_total"] == 3
    assert summary["guardrails"]["pii_redactions_by_type"]["email"] == 2
    assert summary["tokens"]["overall_total"] == 30
    assert summary["latency_ms"]["average"] == 2.5
    assert summary["latency_ms"]["p50"] == 2.5

    # Reset
    metrics.reset()
    reset_summary = metrics.get_summary()
    assert reset_summary["requests"]["total"] == 0
    assert reset_summary["tokens"]["overall_total"] == 0
