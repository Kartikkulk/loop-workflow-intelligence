"""Anthropic wrapper: retry with backoff, cost logging, prompt-hash cache.

Every call site must supply a `fallback` callable. When no API key is set — or
the API fails after all retries — the fallback runs instead. This keeps the
whole product demonstrable offline and means a network problem on stage
degrades output quality rather than breaking the demo.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("loop.llm")

_PROMPT_DIR = Path(__file__).parent / "prompts"

# Approximate USD per million tokens for the default model, used only to give
# the operator a running cost figure in the log.
_COST_IN_PER_MTOK = 3.0
_COST_OUT_PER_MTOK = 15.0


class LLMClient:
    """Thin, dependency-injectable Anthropic client."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._client: Any = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_count = 0
        self.fallback_count = 0

    @property
    def available(self) -> bool:
        return settings.has_llm

    def _ensure_client(self) -> Any:
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.total_input_tokens / 1_000_000 * _COST_IN_PER_MTOK
            + self.total_output_tokens / 1_000_000 * _COST_OUT_PER_MTOK
        )

    @staticmethod
    def load_prompt(template: str, /, **kwargs: Any) -> str:
        """Load a prompt template from llm/prompts/<template>.md and format it.

        Prompts live on disk, never in f-strings, so they can be iterated on
        without touching Python under time pressure.

        `template` is positional-only so that a substitution variable called
        `name` — which several prompts use — cannot collide with it.
        """
        path = _PROMPT_DIR / f"{template}.md"
        text = path.read_text(encoding="utf-8")
        for key, value in kwargs.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
        return text

    async def structured(
        self,
        *,
        prompt: str,
        tool: dict[str, Any],
        fallback: Callable[[], dict[str, Any]],
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Get a structured object out of the model via forced tool use.

        Never parses JSON out of free-form text: the tool schema is the
        contract, so a malformed response is impossible rather than merely
        unlikely.
        """
        cache_key = hashlib.sha256(
            (prompt + json.dumps(tool, sort_keys=True)).encode()
        ).hexdigest()
        if settings.llm_cache and cache_key in self._cache:
            return self._cache[cache_key]

        if not self.available:
            self.fallback_count += 1
            result = fallback()
            if settings.llm_cache:
                self._cache[cache_key] = result
            return result

        last_error: Exception | None = None
        for attempt in range(settings.llm_max_retries):
            try:
                client = self._ensure_client()
                response = await client.messages.create(
                    model=settings.llm_model,
                    max_tokens=max_tokens,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    messages=[{"role": "user", "content": prompt}],
                )
                self.call_count += 1
                self.total_input_tokens += response.usage.input_tokens
                self.total_output_tokens += response.usage.output_tokens
                logger.info(
                    "llm call ok tool=%s in=%d out=%d running_cost=$%.4f",
                    tool["name"],
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    self.estimated_cost_usd,
                )
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        result = dict(block.input)
                        if settings.llm_cache:
                            self._cache[cache_key] = result
                        return result
                raise ValueError("model returned no tool_use block")
            except Exception as exc:  # noqa: BLE001 — any failure must degrade, not crash
                last_error = exc
                backoff = 2**attempt
                logger.warning(
                    "llm call failed (attempt %d/%d): %s — retrying in %ds",
                    attempt + 1,
                    settings.llm_max_retries,
                    exc,
                    backoff,
                )
                if attempt < settings.llm_max_retries - 1:
                    await asyncio.sleep(backoff)

        logger.error("llm exhausted retries, using fallback. last error: %s", last_error)
        self.fallback_count += 1
        result = fallback()
        if settings.llm_cache:
            self._cache[cache_key] = result
        return result

    async def structured_multimodal(
        self,
        *,
        content: list[dict[str, Any]],
        tool: dict[str, Any],
        fallback: Callable[[], dict[str, Any]],
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Structured output from a message containing images as well as text.

        Not cached: the cache key would have to include megabytes of base64, and
        the same frames are never submitted twice in a demo anyway.
        """
        if not self.available:
            self.fallback_count += 1
            return fallback()

        try:
            client = self._ensure_client()
            response = await client.messages.create(
                model=settings.llm_model,
                max_tokens=max_tokens,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": content}],
            )
            self.call_count += 1
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    return dict(block.input)
            raise ValueError("model returned no tool_use block")
        except Exception as exc:  # noqa: BLE001 — degrade, never crash
            logger.error("multimodal call failed: %s — using fallback", exc)
            self.fallback_count += 1
            return fallback()

    async def text(
        self, *, prompt: str, fallback: Callable[[], str], max_tokens: int = 2048
    ) -> str:
        """Get prose out of the model, with the same degrade-not-fail contract."""
        cache_key = hashlib.sha256(("TEXT" + prompt).encode()).hexdigest()
        if settings.llm_cache and cache_key in self._cache:
            return str(self._cache[cache_key]["text"])

        if not self.available:
            self.fallback_count += 1
            return fallback()

        try:
            client = self._ensure_client()
            response = await client.messages.create(
                model=settings.llm_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            self.call_count += 1
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            out = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
            if settings.llm_cache:
                self._cache[cache_key] = {"text": out}
            return out
        except Exception as exc:  # noqa: BLE001
            logger.error("llm text call failed: %s — using fallback", exc)
            self.fallback_count += 1
            return fallback()


llm = LLMClient()
