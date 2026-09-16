from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from guardrail.budget.limiter import BudgetExceededError
from guardrail.chain import GuardrailChain
from guardrail.config import GuardrailConfig, load_config
from guardrail.proxy.forwarder import UpstreamForwarder
from guardrail.proxy.metrics import MetricsCollector
from guardrail.schema.enforcer import SchemaViolationError


def extract_client_id(
    authorization: Optional[str] = None,
    x_client_id: Optional[str] = None,
    client_host: Optional[str] = None,
) -> str:
    """Derives a consistent identifier for per-client rate and token budgeting."""
    if x_client_id:
        return x_client_id
    if authorization:
        # e.g. "Bearer sk-..."
        return authorization.replace("Bearer ", "").strip()
    if client_host:
        return client_host
    return "anonymous_client"


def create_app(
    config: Optional[GuardrailConfig] = None,
    upstream_client: Optional[httpx.AsyncClient] = None,
) -> FastAPI:
    """Constructs a configured FastAPI proxy instance."""
    app_config = config or load_config()
    metrics = MetricsCollector()
    chain = GuardrailChain(app_config)
    forwarder = UpstreamForwarder(chain=chain, metrics=metrics, client=upstream_client)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await forwarder.close()

    app = FastAPI(
        title="guardrail-llm Proxy",
        version="0.1.0",
        description="High-performance, zero-bloat LLM guardrails reverse proxy",
        lifespan=lifespan,
    )

    # Attach state for direct introspection
    app.state.config = app_config
    app.state.metrics = metrics
    app.state.chain = chain
    app.state.forwarder = forwarder

    @app.exception_handler(BudgetExceededError)
    async def budget_exception_handler(request: Request, exc: BudgetExceededError):
        metrics.record_rate_limit_block()
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    @app.exception_handler(SchemaViolationError)
    async def schema_exception_handler(request: Request, exc: SchemaViolationError):
        metrics.record_schema_violation()
        return JSONResponse(
            status_code=400,
            content=exc.to_dict(),
        )

    @app.exception_handler(httpx.HTTPStatusError)
    async def upstream_http_error_handler(request: Request, exc: httpx.HTTPStatusError):
        metrics.record_failure()
        try:
            body = exc.response.json()
        except Exception:
            body = {"error": {"message": exc.response.text, "type": "upstream_error", "code": exc.response.status_code}}
        return JSONResponse(
            status_code=exc.response.status_code,
            content=body,
        )

    @app.exception_handler(httpx.RequestError)
    async def upstream_connect_error_handler(request: Request, exc: httpx.RequestError):
        metrics.record_failure()
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Failed to connect to upstream LLM engine: {exc}",
                    "type": "bad_gateway",
                    "code": "upstream_connection_failed",
                }
            },
        )

    @app.get("/health")
    async def health_check():
        """Health and readiness probe."""
        return {
            "status": "ok",
            "service": "guardrail-llm",
            "version": "0.1.0",
            "upstream": app_config.upstream.base_url,
        }

    @app.get("/metrics")
    async def get_metrics():
        """Prometheus/JSON performance and guardrail metrics."""
        return metrics.get_summary()

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_client_id: Optional[str] = Header(default=None),
    ):
        """OpenAI-compatible chat completions proxy endpoint."""
        client_id = extract_client_id(
            authorization=authorization,
            x_client_id=x_client_id,
            client_host=request.client.host if request.client else None,
        )
        payload = await request.json()

        # Build forward headers
        forward_headers = {}
        if authorization:
            forward_headers["Authorization"] = authorization

        is_stream = bool(payload.get("stream", False))

        if is_stream:
            event_generator = forwarder.forward_streaming(
                endpoint="v1/chat/completions",
                payload=payload,
                client_id=client_id,
                forward_headers=forward_headers,
            )
            return StreamingResponse(
                event_generator,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        result = await forwarder.forward_non_streaming(
            endpoint="v1/chat/completions",
            payload=payload,
            client_id=client_id,
            forward_headers=forward_headers,
        )
        return JSONResponse(content=result)

    @app.post("/v1/completions")
    async def completions(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_client_id: Optional[str] = Header(default=None),
    ):
        """OpenAI-compatible legacy completions proxy endpoint."""
        client_id = extract_client_id(
            authorization=authorization,
            x_client_id=x_client_id,
            client_host=request.client.host if request.client else None,
        )
        payload = await request.json()

        forward_headers = {}
        if authorization:
            forward_headers["Authorization"] = authorization

        is_stream = bool(payload.get("stream", False))

        if is_stream:
            event_generator = forwarder.forward_streaming(
                endpoint="v1/completions",
                payload=payload,
                client_id=client_id,
                forward_headers=forward_headers,
            )
            return StreamingResponse(
                event_generator,
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        result = await forwarder.forward_non_streaming(
            endpoint="v1/completions",
            payload=payload,
            client_id=client_id,
            forward_headers=forward_headers,
        )
        return JSONResponse(content=result)

    return app
