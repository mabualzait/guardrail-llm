from __future__ import annotations

import json
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, Union
from guardrail.budget.limiter import BudgetExceededError, TokenBudgetLimiter
from guardrail.budget.tokenizer import count_prompt_tokens
from guardrail.config import GuardrailConfig
from guardrail.sanitizer.engine import AnonymizationSession, PIISanitizer, StreamingPIISanitizer
from guardrail.schema.enforcer import SchemaEnforcer, SchemaViolationError


class RequestContext:
    """Carries request-scoped state through the guardrail lifecycle."""

    def __init__(self, client_id: str, session: AnonymizationSession) -> None:
        self.client_id = client_id
        self.session = session
        self.start_time: float = time.perf_counter()
        self.estimated_prompt_tokens: int = 0
        self.actual_total_tokens: int = 0
        self.was_repaired: bool = False
        self.model: str = ""
        self.is_chat: bool = True
        self.is_stream: bool = False


class GuardrailChain:
    """Core interceptor orchestrator for inbound and outbound LLM traffic."""

    def __init__(self, config: Optional[GuardrailConfig] = None) -> None:
        self.config = config or GuardrailConfig()
        self.sanitizer = PIISanitizer(self.config.pii)
        self.schema_enforcer = SchemaEnforcer(self.config.schema_rule)
        self.limiter = TokenBudgetLimiter(self.config.budget)

    def prepare_inbound(
        self,
        payload: Dict[str, Any],
        client_id: str = "default_client",
    ) -> Tuple[Dict[str, Any], RequestContext]:
        """Runs inbound guardrails: token budget check + PII masking."""
        session = self.sanitizer.create_session()
        ctx = RequestContext(client_id=client_id, session=session)
        ctx.model = payload.get("model", "")
        ctx.is_stream = bool(payload.get("stream", False))

        # 1. Budget estimation
        prompt_data = payload.get("messages") or payload.get("prompt")
        if prompt_data:
            ctx.is_chat = "messages" in payload
            ctx.estimated_prompt_tokens = count_prompt_tokens(prompt_data)
            # Budget check & reserve
            self.limiter.check_and_reserve(client_id, ctx.estimated_prompt_tokens)

        # 2. PII Sanitization
        sanitized_payload = dict(payload)
        if "messages" in sanitized_payload and isinstance(sanitized_payload["messages"], list):
            sanitized_payload["messages"] = self.sanitizer.sanitize_messages(
                sanitized_payload["messages"], session
            )
        elif "prompt" in sanitized_payload:
            sanitized_payload["prompt"] = self.sanitizer.sanitize_prompt(
                sanitized_payload["prompt"], session
            )

        return sanitized_payload, ctx

    async def process_outbound(
        self,
        response_payload: Dict[str, Any],
        ctx: RequestContext,
        repair_callback: Optional[Callable[[str, List[str]], Coroutine[Any, Any, str]]] = None,
    ) -> Dict[str, Any]:
        """Runs outbound guardrails: JSON repair/validation + de-anonymization + token settlement."""
        processed = dict(response_payload)

        # 1. Process chat completions or legacy completions content
        choices = processed.get("choices")
        if isinstance(choices, list) and choices:
            for choice in choices:
                if "message" in choice and isinstance(choice["message"], dict):
                    content = choice["message"].get("content")
                    if isinstance(content, str):
                        # Schema / JSON repair pass
                        if self.schema_enforcer.is_active:
                            content, was_repaired = await self.schema_enforcer.enforce_async(
                                content, repair_callback=repair_callback
                            )
                            ctx.was_repaired = ctx.was_repaired or was_repaired

                        # Outbound De-anonymization / Restoration
                        if self.config.pii.reversible:
                            content = ctx.session.deanonymize(content)

                        choice["message"]["content"] = content

                elif "text" in choice and isinstance(choice["text"], str):
                    content = choice["text"]
                    if self.schema_enforcer.is_active:
                        content, was_repaired = await self.schema_enforcer.enforce_async(
                            content, repair_callback=repair_callback
                        )
                        ctx.was_repaired = ctx.was_repaired or was_repaired

                    if self.config.pii.reversible:
                        content = ctx.session.deanonymize(content)

                    choice["text"] = content

        # 2. Settle actual token usage
        usage = processed.get("usage")
        if isinstance(usage, dict) and "total_tokens" in usage:
            actual_tokens = int(usage["total_tokens"])
            ctx.actual_total_tokens = actual_tokens
            self.limiter.record_usage(ctx.client_id, actual_tokens)
        elif ctx.estimated_prompt_tokens > 0:
            # Fallback settlement using estimated prompt tokens
            self.limiter.record_usage(ctx.client_id, ctx.estimated_prompt_tokens)

        return processed

    def create_streaming_sanitizer(self, ctx: RequestContext) -> StreamingPIISanitizer:
        """Instantiates a chunk buffer for SSE streaming."""
        return StreamingPIISanitizer(self.sanitizer, ctx.session)
