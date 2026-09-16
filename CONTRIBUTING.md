# Contributing to `guardrail-llm`

Thank you for your interest in contributing to **`guardrail-llm`**, maintained by **[Malik Abualzait](https://github.com/mabualzait)**!

We welcome community contributions, including new PII patterns, speed optimizations, bug fixes, and documentation improvements.

---

## 🛠️ Local Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/mabualzait/guardrail-llm.git
   cd guardrail-llm
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

3. **Run the test suite:**
   ```bash
   pytest -v --cov=guardrail --cov-report=term-missing
   ```

4. **Run the latency benchmark:**
   ```bash
   python benchmarks/benchmark_latency.py
   ```

---

## 📐 Development Guidelines

- **Zero Bloat Policy:** Do not introduce heavy runtime dependencies (e.g. transformers, spacy, torch). All core logic should remain ultra-lightweight and deterministic.
- **Latency Budget:** Any change to the core interception pipeline must maintain added latency under 5ms (target: < 0.1ms).
- **Test Coverage:** All new features must include unit and integration tests maintaining overall coverage above 85%.

---

## 🤝 Submitting Changes

1. Fork the repository and create your feature branch:
   ```bash
   git checkout -b feature/my-enhancement
   ```
2. Ensure all tests pass.
3. Commit your changes with clear, descriptive commit messages.
4. Open a Pull Request on GitHub.

Thank you for helping make `guardrail-llm` faster and safer!
