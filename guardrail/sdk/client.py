from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Union
import httpx
from guardrail.chain import GuardrailChain
from guardrail.config import GuardrailConfig, PIICustomPattern, load_config
from guardrail.proxy.forwarder import UpstreamForwarder
from guardrail.proxy.metrics import MetricsCollector


class _ChatCompletions:
    def __init__(self, client: GuardrailedClient) -> None:
        self._client = client

    def create(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        client_id: str = "sdk_client",
        stream: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Synchronously executes a guarded chat completion."""
        payload = {"model": model, "messages": messages, "stream": stream, **kwargs}
        return self._client._run_sync(
            self._client._forwarder.forward_non_streaming(
                endpoint="v1/chat/completions",
                payload=payload,
                client_id=client_id,
            )
        )

    async def acreate(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        client_id: str = "sdk_client",
        stream: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Asynchronously executes a guarded chat completion."""
        payload = {"model": model, "messages": messages, "stream": stream, **kwargs}
        return await self._client._forwarder.forward_non_streaming(
            endpoint="v1/chat/completions",
            payload=payload,
            client_id=client_id,
        )


class _Chat:
    def __init__(self, client: GuardrailedClient) -> None:
        self.completions = _ChatCompletions(client)


class _Completions:
    def __init__(self, client: GuardrailedClient) -> None:
        self._client = client

    def create(
        self,
        *,
        model: str,
        prompt: Union[str, List[str]],
        client_id: str = "sdk_client",
        stream: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload = {"model": model, "prompt": prompt, "stream": stream, **kwargs}
        return self._client._run_sync(
            self._client._forwarder.forward_non_streaming(
                endpoint="v1/completions",
                payload=payload,
                client_id=client_id,
            )
        )

    async def acreate(
        self,
        *,
        model: str,
        prompt: Union[str, List[str]],
        client_id: str = "sdk_client",
        stream: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload = {"model": model, "prompt": prompt, "stream": stream, **kwargs}
        return await self._client._forwarder.forward_non_streaming(
            endpoint="v1/completions",
            payload=payload,
            client_id=client_id,
        )


class GuardrailedClient:
    """Drop-in SDK client wrapping upstream LLM engines with local guardrails."""

    def __init__(
        self,
        upstream_url: Optional[str] = None,
        config: Optional[Union[str, GuardrailConfig, Dict[str, Any]]] = None,
        pii: Optional[bool] = None,
        strict_json: Optional[bool] = None,
        schema: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
        httpx_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if config is None:
            self.config = GuardrailConfig()
        else:
            self.config = load_config(config)

        if upstream_url:
            self.config.upstream.base_url = upstream_url
        if headers:
            self.config.upstream.headers.update(headers)
        if timeout:
            self.config.upstream.timeout = timeout
        if pii is not None:
            self.config.pii.enabled = pii
        if strict_json is not None:
            self.config.schema_rule.strict_json = strict_json
        if schema is not None:
            self.config.schema_rule.enabled = True
            self.config.schema_rule.schema_definition = schema

        self.metrics = MetricsCollector()
        self.chain = GuardrailChain(self.config)
        self._forwarder = UpstreamForwarder(
            chain=self.chain,
            metrics=self.metrics,
            client=httpx_client,
        )

        self.chat = _Chat(self)
        self.completions = _Completions(self)

    def _run_sync(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # If already running inside an active event loop (e.g. Jupyter or nested loop), run in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: asyncio.run(coro))
                return future.result()
        return asyncio.run(coro)

    async def aclose(self) -> None:
        await self._forwarder.close()

    def close(self) -> None:
        self._run_sync(self.aclose())

    def __enter__(self) -> GuardrailedClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    async def __aenter__(self) -> GuardrailedClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()
