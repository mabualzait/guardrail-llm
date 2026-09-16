from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional
import httpx
from guardrail.chain import GuardrailChain, RequestContext
from guardrail.proxy.metrics import MetricsCollector
from guardrail.schema.enforcer import SchemaViolationError


class UpstreamForwarder:
    """Dispatches sanitized requests to upstream LLMs and applies outbound guardrails."""

    def __init__(
        self,
        chain: GuardrailChain,
        metrics: MetricsCollector,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.chain = chain
        self.config = chain.config
        self.metrics = metrics
        self._client = client
        self._owns_client = client is None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.upstream.timeout),
                headers=self.config.upstream.headers,
            )
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client and not self._client.is_closed:
            await self._client.aclose()

    def _resolve_upstream_url(self, endpoint: str) -> str:
        base = self.config.upstream.base_url.rstrip("/")
        ep = endpoint.lstrip("/")
        # If base already ends with /v1 and ep starts with v1/, avoid duplicate
        if base.endswith("/v1") and ep.startswith("v1/"):
            ep = ep[3:]
        return f"{base}/{ep}"

    async def forward_non_streaming(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        client_id: str = "default_client",
        forward_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Forwards non-streaming completion request with full guardrail lifecycle."""
        self.metrics.record_request_start()
        start_time = time.perf_counter()

        # Inbound pipeline
        sanitized_payload, ctx = self.chain.prepare_inbound(payload, client_id=client_id)
        if ctx.session.detection_counts:
            self.metrics.record_pii_detections(ctx.session.detection_counts)

        url = self._resolve_upstream_url(endpoint)
        client = await self.get_client()

        # Define 1-shot self-repair callback if needed
        async def repair_callback(faulty_content: str, errors: List[str]) -> str:
            repair_prompt = (
                f"You produced the following JSON output which is invalid or does not match the required schema:\n"
                f"```json\n{faulty_content}\n```\n\n"
                f"Validation errors:\n" + "\n".join(f"- {e}" for e in errors) + "\n\n"
                f"Please fix and output ONLY the corrected, valid JSON. Do not include explanation."
            )
            repair_payload = dict(sanitized_payload)
            if "messages" in repair_payload:
                repair_payload["messages"] = list(repair_payload["messages"]) + [
                    {"role": "assistant", "content": faulty_content},
                    {"role": "user", "content": repair_prompt},
                ]
            elif "prompt" in repair_payload:
                repair_payload["prompt"] = f"{faulty_content}\n\n{repair_prompt}"

            self.metrics.record_schema_repair()
            retry_res = await client.post(url, json=repair_payload, headers=forward_headers or {})
            retry_res.raise_for_status()
            retry_data = retry_res.json()

            # Extract content from response
            choices = retry_data.get("choices", [])
            if choices:
                c = choices[0]
                if "message" in c:
                    return c["message"].get("content", "")
                if "text" in c:
                    return c.get("text", "")
            return ""

        try:
            upstream_res = await client.post(url, json=sanitized_payload, headers=forward_headers or {})
            upstream_res.raise_for_status()
            response_json = upstream_res.json()

            # Outbound pipeline
            final_response = await self.chain.process_outbound(
                response_json, ctx, repair_callback=repair_callback
            )

            if ctx.was_repaired:
                self.metrics.record_schema_repair()

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            usage = final_response.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", ctx.estimated_prompt_tokens)
            completion_tokens = usage.get("completion_tokens", 0)

            self.metrics.record_success(
                elapsed_ms, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
            )
            return final_response

        except SchemaViolationError as err:
            self.metrics.record_schema_violation()
            self.metrics.record_failure()
            raise err
        except Exception as e:
            self.metrics.record_failure()
            raise e

    async def forward_streaming(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        client_id: str = "default_client",
        forward_headers: Optional[Dict[str, str]] = None,
    ) -> AsyncIterator[str]:
        """Streams Server-Sent Events (SSE) from upstream, sanitizing tokens in transit."""
        self.metrics.record_request_start()
        start_time = time.perf_counter()

        sanitized_payload, ctx = self.chain.prepare_inbound(payload, client_id=client_id)
        if ctx.session.detection_counts:
            self.metrics.record_pii_detections(ctx.session.detection_counts)

        url = self._resolve_upstream_url(endpoint)
        client = await self.get_client()
        stream_sanitizer = self.chain.create_streaming_sanitizer(ctx)

        headers = dict(forward_headers or {})
        headers["Accept"] = "text/event-stream"

        accumulated_chunks = 0
        try:
            async with client.stream("POST", url, json=sanitized_payload, headers=headers) as upstream_response:
                upstream_response.raise_for_status()

                async for line in upstream_response.aiter_lines():
                    if not line:
                        yield "\n"
                        continue

                    if not line.startswith("data:"):
                        yield f"{line}\n"
                        continue

                    data_payload = line[5:].strip()
                    if data_payload == "[DONE]":
                        # Flush remaining buffer in stream sanitizer
                        flushed = stream_sanitizer.flush()
                        if flushed:
                            # If reversible, deanonymize
                            if self.config.pii.reversible:
                                flushed = ctx.session.deanonymize(flushed)

                            flush_chunk = {
                                "id": f"chatcmpl-stream-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": ctx.model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": flushed},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(flush_chunk)}\n\n"

                        yield "data: [DONE]\n\n"
                        break

                    try:
                        chunk_dict = json.loads(data_payload)
                        choices = chunk_dict.get("choices", [])
                        if choices and "delta" in choices[0] and "content" in choices[0]["delta"]:
                            raw_piece = choices[0]["delta"]["content"]
                            if raw_piece:
                                safe_piece = stream_sanitizer.process_chunk(raw_piece)
                                if self.config.pii.reversible and safe_piece:
                                    safe_piece = ctx.session.deanonymize(safe_piece)

                                choices[0]["delta"]["content"] = safe_piece
                                yield f"data: {json.dumps(chunk_dict)}\n\n"
                                accumulated_chunks += 1
                                continue

                        yield f"data: {data_payload}\n\n"
                    except Exception:
                        yield f"{line}\n"

            # Record metrics
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self.metrics.record_success(
                elapsed_ms,
                prompt_tokens=ctx.estimated_prompt_tokens,
                completion_tokens=accumulated_chunks,
            )
            # Settle tokens in limiter
            self.chain.limiter.record_usage(
                client_id, ctx.estimated_prompt_tokens + accumulated_chunks
            )

        except Exception as e:
            self.metrics.record_failure()
            raise e
