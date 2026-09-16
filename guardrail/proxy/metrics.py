from __future__ import annotations

import threading
import time
from typing import Any, Deque, Dict, List
import collections


class MetricsCollector:
    """Thread-safe metrics accumulator for proxy operations and guardrails."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.start_time: float = time.time()
        self.total_requests: int = 0
        self.successful_requests: int = 0
        self.failed_requests: int = 0
        self.blocked_by_rate_limit: int = 0
        self.schema_violations: int = 0
        self.schema_repairs: int = 0
        self.pii_redactions_total: int = 0
        self.pii_redactions_by_type: Dict[str, int] = collections.defaultdict(int)
        self.tokens_prompt_total: int = 0
        self.tokens_completion_total: int = 0
        self.tokens_overall_total: int = 0
        # Latencies in milliseconds (last 1000 requests)
        self.latencies_ms: Deque[float] = collections.deque(maxlen=1000)

    def record_request_start(self) -> None:
        with self._lock:
            self.total_requests += 1

    def record_success(self, duration_ms: float, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        with self._lock:
            self.successful_requests += 1
            self.latencies_ms.append(duration_ms)
            self.tokens_prompt_total += prompt_tokens
            self.tokens_completion_total += completion_tokens
            self.tokens_overall_total += (prompt_tokens + completion_tokens)

    def record_failure(self) -> None:
        with self._lock:
            self.failed_requests += 1

    def record_rate_limit_block(self) -> None:
        with self._lock:
            self.blocked_by_rate_limit += 1
            self.failed_requests += 1

    def record_pii_detections(self, detections: Dict[str, int]) -> None:
        with self._lock:
            for cat, count in detections.items():
                self.pii_redactions_by_type[cat] += count
                self.pii_redactions_total += count

    def record_schema_repair(self) -> None:
        with self._lock:
            self.schema_repairs += 1

    def record_schema_violation(self) -> None:
        with self._lock:
            self.schema_violations += 1

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            uptime = time.time() - self.start_time
            latencies = sorted(list(self.latencies_ms))
            n = len(latencies)

            p50 = latencies[int(n * 0.50)] if n > 0 else 0.0
            p90 = latencies[int(n * 0.90)] if n > 0 else 0.0
            p99 = latencies[int(n * 0.99)] if n > 0 else 0.0
            avg_lat = sum(latencies) / n if n > 0 else 0.0

            return {
                "uptime_seconds": round(uptime, 2),
                "requests": {
                    "total": self.total_requests,
                    "successful": self.successful_requests,
                    "failed": self.failed_requests,
                    "blocked_rate_limit": self.blocked_by_rate_limit,
                },
                "guardrails": {
                    "pii_redactions_total": self.pii_redactions_total,
                    "pii_redactions_by_type": dict(self.pii_redactions_by_type),
                    "schema_repairs": self.schema_repairs,
                    "schema_violations": self.schema_violations,
                },
                "tokens": {
                    "prompt_total": self.tokens_prompt_total,
                    "completion_total": self.tokens_completion_total,
                    "overall_total": self.tokens_overall_total,
                },
                "latency_ms": {
                    "count": n,
                    "average": round(avg_lat, 2),
                    "p50": round(p50, 2),
                    "p90": round(p90, 2),
                    "p99": round(p99, 2),
                },
            }

    def reset(self) -> None:
        with self._lock:
            self.start_time = time.time()
            self.total_requests = 0
            self.successful_requests = 0
            self.failed_requests = 0
            self.blocked_by_rate_limit = 0
            self.schema_violations = 0
            self.schema_repairs = 0
            self.pii_redactions_total = 0
            self.pii_redactions_by_type.clear()
            self.tokens_prompt_total = 0
            self.tokens_completion_total = 0
            self.tokens_overall_total = 0
            self.latencies_ms.clear()
