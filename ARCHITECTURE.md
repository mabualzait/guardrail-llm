# Architecture Specification: `guardrail-llm`

> Designed & Architected by **[Malik Abualzait](https://github.com/mabualzait)**

`guardrail-llm` is engineered to eliminate the high latency and operational complexity associated with monolithic AI guardrail frameworks. By operating as a zero-bloat asynchronous reverse proxy and embeddable SDK, it achieves sub-millisecond execution times (< 0.05 ms) while enforcing data privacy, structural schema guarantees, and token budget governance.

---

## 1. System Pipeline Overview

```
                      +-----------------------------+
                      |   Client Application / SDK  |
                      +-----------------------------+
                                     |
                                     v
                       POST /v1/chat/completions
                                     |
+------------------------------------+------------------------------------+
| Guardrail Pipeline Execution Context                                   |
|                                                                         |
|  [Inbound Interceptors]                                                 |
|    1. Sliding Window Token Budget Check & Pre-reservation               |
|    2. Reversible PII Redaction Engine (Linear O(N) Regex Scanner)       |
|                                                                         |
|  [Async Upstream Dispatch]                                              |
|    3. High-throughput HTTP Forwarder (Ollama / vLLM / OpenAI / etc.)    |
|                                                                         |
|  [Outbound Interceptors]                                                |
|    4. JSON Code Block Extraction & Auto-Healing Repair Pass             |
|    5. JSON Schema Validation Engine (with optional 1-shot retry)        |
|    6. De-anonymization & Token Settlement Pass                          |
+------------------------------------+------------------------------------+
                                     |
                                     v
                        OpenAI-Compatible Response
```

---

## 2. Core Modules Deep Dive

### 2.1 PII Sanitization Engine (`guardrail.sanitizer`)
- **Linear-Time $O(N)$ Scanning**: Pre-compiled regular expressions carefully avoid nested quantifiers (`(a+)+`), ensuring immunity to catastrophic backtracking (ReDoS attacks).
- **Precedence Hierarchy**: Rules are evaluated in strict priority order (`api_key` $\rightarrow$ `credit_card` $\rightarrow$ `ipv4` $\rightarrow$ `ssn` $\rightarrow$ `email` $\rightarrow$ `phone`) to prevent ambiguous substring collisions (e.g. IP addresses mistaken for telephone segments).
- **Luhn Algorithmic Verification**: Credit card candidates must pass a modulo-10 Luhn checksum before redaction.
- **Reversible Token Maps**: Each unique entity is assigned a persistent session tag (`[EMAIL_1]`, `[PHONE_1]`). Upon receiving the LLM response, placeholders can be seamlessly restored to their original values if `reversible: true`.
- **SSE Stream Windowing**: The `StreamingPIISanitizer` holds a trailing sliding buffer split on whitespace delimiters to ensure entities cut across Server-Sent Events chunk boundaries are safely redacted.

### 2.2 Schema Enforcement & Auto-Healing Engine (`guardrail.schema`)
- **Markdown Stripping**: Automatically extracts embedded payloads from ```` ```json ... ``` ```` or surrounding conversational text.
- **Deterministic Zero-Dependency Repair Pass**:
  - Cleans JavaScript-style inline (`//`) and multiline (`/* */`) comments.
  - Fixes Python literal capitalization (`True` $\rightarrow$ `true`, `None` $\rightarrow$ `null`).
  - Converts single quotes to double quotes without breaking inner contractions.
  - Strips illegal trailing commas before closing braces.
  - Auto-closes unclosed double-quotes, arrays, and object braces in exact LIFO stack order.
- **Lightweight Validator**: Validates recursive object properties, required keys, enums, array items, and min/max constraints without requiring third-party dependencies.
- **1-Shot Self-Healing Retry Loop**: If validation fails and `on_failure="retry"`, the forwarder initiates a single automated zero-shot repair prompt to upstream before surfacing an error.

### 2.3 Token Budgeting & Sliding Window Meter (`guardrail.budget`)
- **Deterministic Token Estimation**: High-precision boundary tokenizer approximating BPE encoding (~3.8 characters per token) with zero dependencies, plus native `tiktoken` acceleration when installed.
- **Sliding Window Accumulator**: Thread-safe per-client deques tracking timestamps and actual usage.
- **Rate Governance**: Rejects traffic immediately with `429 Too Many Requests` or `402 Payment Required` when limits are breached.
- **Upstream Usage Settlement**: Accurately reconciles pre-estimated tokens with actual `usage.total_tokens` reported by upstream engines.

---

## 3. Dual Deployment Topology

1. **Proxy Sidecar Daemon**: Ideal for containerized microservice architectures (Docker, Kubernetes sidecars) where multiple services share a single upstream model endpoint.
2. **Embedded Python SDK**: Direct integration within application threads via `GuardrailedClient`, executing guardrails in-process without introducing extra network hops.

---

## 4. Benchmark Validation

Micro-benchmarks measuring 1,000 requests against a standard baseline:
- **Throughput**: ~39,700 requests/second
- **Average Added Latency**: **0.025 milliseconds (25 µs)**
- **P99 Added Latency**: **0.035 milliseconds (35 µs)**

Architected by **Malik Abualzait**.
