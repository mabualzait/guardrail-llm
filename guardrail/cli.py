from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional
import uvicorn
from guardrail.config import GuardrailConfig, load_config
from guardrail.proxy.app import create_app

BANNER = r"""
  ____                     _           _ _       _     _     __  __ 
 / ___|_   _  __ _ _ __ __| |_ __ __ _(_) |     | |   | |   |  \/  |
| |  _| | | |/ _` | '__/ _` | '__/ _` | | |_____| |   | |   | |\/| |
| |_| | |_| | (_| | | | (_| | | | (_| | | |_____| |___| |___| |  | |
 \____|\__,_|\__,_|_|  \__,_|_|  \__,_|_|_|     |_____|_____|_|  |_|
              High-Performance Guardrails Proxy & SDK
"""


def main(args: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="guardrail",
        description="guardrail-llm: High-performance, zero-bloat LLM guardrails reverse proxy and SDK.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # `run` command
    run_parser = subparsers.add_parser("run", help="Start the guardrail reverse proxy daemon")
    run_parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to guardrail.yaml configuration file",
    )
    run_parser.add_argument(
        "--host",
        "-H",
        type=str,
        default=None,
        help="Host address to bind to (overrides config, default 0.0.0.0)",
    )
    run_parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=None,
        help="Port number to listen on (overrides config, default 8080)",
    )
    run_parser.add_argument(
        "--upstream",
        "-u",
        type=str,
        default=None,
        help="Upstream LLM engine base URL (e.g. http://localhost:11434/v1)",
    )
    run_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=None,
        help="Number of worker processes",
    )
    run_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for local development",
    )

    parsed_args = parser.parse_args(args)

    if not parsed_args.command:
        parser.print_help()
        sys.exit(0)

    if parsed_args.command == "run":
        # Load configuration
        config_path = parsed_args.config
        if config_path is None and Path("guardrail.yaml").exists():
            config_path = "guardrail.yaml"

        cfg = load_config(config_path) if config_path else GuardrailConfig()

        # Command line overrides
        if parsed_args.host:
            cfg.server.host = parsed_args.host
        if parsed_args.port:
            cfg.server.port = parsed_args.port
        if parsed_args.upstream:
            cfg.upstream.base_url = parsed_args.upstream
        if parsed_args.workers:
            cfg.server.workers = parsed_args.workers

        print(BANNER)
        print(f"  [+] Proxy Listening on:  http://{cfg.server.host}:{cfg.server.port}")
        print(f"  [+] Upstream Target:     {cfg.upstream.base_url}")
        print(f"  [+] PII Guardrail:       {'ENABLED (reversible=' + str(cfg.pii.reversible) + ')' if cfg.pii.enabled else 'DISABLED'}")
        print(f"  [+] Schema Enforcement:  {'ENABLED (strict=' + str(cfg.schema_rule.strict_json) + ')' if cfg.schema_rule.enabled or cfg.schema_rule.strict_json else 'DISABLED'}")
        print(f"  [+] Token Budgeting:     {'ENABLED (max ' + str(cfg.budget.max_tokens_per_minute) + ' tok/min)' if cfg.budget.enabled else 'DISABLED'}")
        print(f"  [+] Endpoints:           /v1/chat/completions, /v1/completions, /health, /metrics\n")

        app = create_app(cfg)
        uvicorn.run(
            app,
            host=cfg.server.host,
            port=cfg.server.port,
            workers=cfg.server.workers,
            reload=parsed_args.reload,
            log_level="info",
        )


if __name__ == "__main__":
    main()
