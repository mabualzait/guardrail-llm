# Changelog

All notable changes to **`guardrail-llm`** will be documented in this file.

Project Maintainer: **[Malik Abualzait](https://github.com/mabualzait)**

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-09-16

### Added
- **Reverse Proxy**: Transparent OpenAI `/v1/chat/completions` and `/v1/completions` endpoints with SSE streaming.
- **Observability**: Added `/health` readiness check and `/metrics` real-time telemetry endpoint.
- **PII Engine**: Linear-time $O(N)$ scanning with reversible tags for Email, Phone, Luhn-verified Credit Cards, IPv4, SSN, and API Keys.
- **Schema Auto-Healing**: Zero-dependency deterministic JSON repair pass for markdown blocks, single quotes, trailing commas, comments, and unclosed braces.
- **Token Budgeting**: Sliding-window rate limiting with `429` and `402` HTTP enforcement and upstream token reconciliation.
- **Dual Deployment**: Standalone CLI runner (`guardrail run`) and embedded Python SDK (`GuardrailedClient`).
- **Benchmark Suite**: Verified 0.025 ms added latency overhead (< 5ms acceptance requirement).
