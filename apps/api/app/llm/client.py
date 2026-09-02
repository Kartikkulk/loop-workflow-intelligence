"""LLM wrapper: retry with backoff, prompt-hash cache, safe fallback.

Supports:
- LOOP_LLM_PROVIDER=ollama (local, default)
- LOOP_LLM_PROVIDER=gemini (Google GenAI SDK, gemini-2.5-flash)

Every call site must supply a `fallback` callable. Failures degrade to the
fallback instead of crashing the product.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("loop.llm")

_PROMPT_DIR = Path(__file__).parent / "prompts"

_JSON_INSTRUCTION = (
    "Return only a JSON object that matches the provided schema. "
    "Do not include markdown, commentary, or extra keys."
)

_SECRET_RE = re.compile(
    r"(AIza[A-Za-z0-9_-]{8,}|key=[A-Za-z0-9_-]{8,}|Bearer [A-Za-z0-9._-]+)",
    re.IGNORECASE,
)


def _provider() -> str:
    return settings.llm_provider.strip().lower()


def _prepare_gemini_ssl() -> None:
    """Use the OS certificate store so Windows/corporate TLS succeeds."""
    import os

    import certifi
    import truststore

    truststore.inject_into_ssl()
    bundle = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)


def redact_secrets(text: str) -> str:
    """Strip API keys from strings before logging or raising."""
    out = text
    key = (settings.gemini_api_key or "").strip()
    if key:
        out = out.replace(key, "[redacted]")
    return _SECRET_RE.sub("[redacted]", out)


class LLMClient:
    """Thin, dependency-injectable LLM client (Ollama or Gemini)."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_count = 0
        self.fallback_count = 0

    @property
    def available(self) -> bool:
        return settings.has_llm

    @property
    def vision_available(self) -> bool:
        return settings.has_vision_llm

    @property
    def estimated_cost_usd(self) -> float:
        return 0.0

    @staticmethod
    def _ollama_chat(payload: dict[str, Any]) -> dict[str, Any]:
        url = settings.ollama_base_url.rstrip("/") + "/api/chat"
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = redact_secrets(exc.read().decode(errors="replace"))
            raise RuntimeError(f"ollama returned HTTP {exc.code}: {detail}") from exc

    async def _chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._ollama_chat, payload)

    def _record_usage(self, response: dict[str, Any]) -> None:
        self.call_count += 1
        self.total_input_tokens += int(response.get("prompt_eval_count") or 0)
        self.total_output_tokens += int(response.get("eval_count") or 0)

    @staticmethod
    def _message_text(response: dict[str, Any]) -> str:
        message = response.get("message") or {}
        return str(message.get("content") or "")

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

    def _gemini_generate_content(
        self, *, prompt: str, schema: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        """Call the official Google GenAI SDK. Overridable in tests."""
        from google import genai

        _prepare_gemini_ssl()
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.llm_model,
            contents=f"{prompt}\n\n{_JSON_INSTRUCTION}",
            config={
                "temperature": 0,
                "max_output_tokens": max_tokens,
                "response_mime_type": "application/json",
                "response_json_schema": schema,
                "automatic_function_calling": {"disable": True},
            },
        )
        usage = getattr(response, "usage_metadata", None)
        return {
            "text": str(getattr(response, "text", None) or ""),
            "parsed": getattr(response, "parsed", None),
            "prompt_eval_count": int(getattr(usage, "prompt_token_count", 0) or 0),
            "eval_count": int(getattr(usage, "candidates_token_count", 0) or 0),
        }

    def _gemini_generate_text(self, *, prompt: str, max_tokens: int) -> dict[str, Any]:
        """Plain-text Gemini call. Overridable in tests."""
        from google import genai

        _prepare_gemini_ssl()
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.llm_model,
            contents=prompt,
            config={"temperature": 0.2, "max_output_tokens": max_tokens},
        )
        usage = getattr(response, "usage_metadata", None)
        return {
            "text": str(getattr(response, "text", None) or ""),
            "parsed": None,
            "prompt_eval_count": int(getattr(usage, "prompt_token_count", 0) or 0),
            "eval_count": int(getattr(usage, "candidates_token_count", 0) or 0),
        }

    async def _structured_gemini(
        self, *, prompt: str, schema: dict[str, Any], tool_name: str, max_tokens: int
    ) -> dict[str, Any]:
        raw = await asyncio.to_thread(
            self._gemini_generate_content,
            prompt=prompt,
            schema=schema,
            max_tokens=max_tokens,
        )
        self._record_usage(raw)
        parsed = raw.get("parsed")
        result = parsed if isinstance(parsed, dict) else json.loads(str(raw.get("text") or ""))
        if not isinstance(result, dict):
            raise ValueError("model returned a non-object JSON value")
        logger.info(
            "llm call ok provider=gemini model=%s tool=%s in=%d out=%d",
            settings.llm_model,
            tool_name,
            int(raw.get("prompt_eval_count") or 0),
            int(raw.get("eval_count") or 0),
        )
        return result

    async def _structured_ollama(
        self, *, prompt: str, schema: dict[str, Any], tool_name: str, max_tokens: int
    ) -> dict[str, Any]:
        response = await self._chat(
            {
                "model": settings.llm_model,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"{prompt}\n\n{_JSON_INSTRUCTION}\n\n"
                            f"Schema:\n{json.dumps(schema, indent=2)}"
                        ),
                    }
                ],
                "stream": False,
                "format": schema,
                "options": {"temperature": 0, "num_predict": max_tokens},
            }
        )
        self._record_usage(response)
        logger.info(
            "llm call ok provider=ollama model=%s tool=%s in=%d out=%d",
            settings.llm_model,
            tool_name,
            int(response.get("prompt_eval_count") or 0),
            int(response.get("eval_count") or 0),
        )
        result = json.loads(self._message_text(response))
        if not isinstance(result, dict):
            raise ValueError("model returned a non-object JSON value")
        return result

    async def structured(
        self,
        *,
        prompt: str,
        tool: dict[str, Any],
        fallback: Callable[[], dict[str, Any]],
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Get a structured object out of the configured provider.

        Ollama and Gemini both receive the tool JSON schema. The response is
        parsed defensively, and any failure falls back.
        """
        cache_key = hashlib.sha256(
            (
                _provider()
                + settings.llm_model
                + prompt
                + json.dumps(tool, sort_keys=True)
            ).encode()
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
        schema = dict(tool["input_schema"])
        for attempt in range(settings.llm_max_retries):
            try:
                if _provider() == "gemini":
                    result = await self._structured_gemini(
                        prompt=prompt,
                        schema=schema,
                        tool_name=tool["name"],
                        max_tokens=max_tokens,
                    )
                else:
                    result = await self._structured_ollama(
                        prompt=prompt,
                        schema=schema,
                        tool_name=tool["name"],
                        max_tokens=max_tokens,
                    )
                if settings.llm_cache:
                    self._cache[cache_key] = result
                return result
            except Exception as exc:  # noqa: BLE001 — any failure must degrade, not crash
                last_error = exc
                backoff = 2**attempt
                logger.warning(
                    "llm call failed (attempt %d/%d): %s — retrying in %ds",
                    attempt + 1,
                    settings.llm_max_retries,
                    redact_secrets(str(exc)),
                    backoff,
                )
                if attempt < settings.llm_max_retries - 1:
                    await asyncio.sleep(backoff)

        logger.error(
            "llm exhausted retries, using fallback. last error: %s",
            redact_secrets(str(last_error)),
        )
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
        Vision remains Ollama-only.
        """
        if not self.vision_available:
            self.fallback_count += 1
            return fallback()

        try:
            text_parts: list[str] = []
            images: list[str] = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text") or ""))
                elif block.get("type") == "image":
                    source = block.get("source") or {}
                    data = str(source.get("data") or "")
                    if data:
                        images.append(data)
            schema = dict(tool["input_schema"])
            response = await self._chat(
                {
                    "model": settings.ollama_vision_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "\n\n".join(text_parts)
                                + f"\n\n{_JSON_INSTRUCTION}\n\n"
                                + f"Schema:\n{json.dumps(schema, indent=2)}"
                            ),
                            "images": images,
                        }
                    ],
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0, "num_predict": max_tokens},
                }
            )
            self._record_usage(response)
            result = json.loads(self._message_text(response))
            if not isinstance(result, dict):
                raise ValueError("model returned a non-object JSON value")
            return result
        except Exception as exc:  # noqa: BLE001 — degrade, never crash
            logger.error("multimodal call failed: %s — using fallback", redact_secrets(str(exc)))
            self.fallback_count += 1
            return fallback()

    async def text(
        self, *, prompt: str, fallback: Callable[[], str], max_tokens: int = 2048
    ) -> str:
        """Get prose out of the model, with the same degrade-not-fail contract."""
        cache_key = hashlib.sha256(
            ("TEXT" + _provider() + settings.llm_model + prompt).encode()
        ).hexdigest()
        if settings.llm_cache and cache_key in self._cache:
            return str(self._cache[cache_key]["text"])

        if not self.available:
            self.fallback_count += 1
            return fallback()

        try:
            if _provider() == "gemini":
                raw = await asyncio.to_thread(
                    self._gemini_generate_text,
                    prompt=prompt,
                    max_tokens=max_tokens,
                )
                self._record_usage(raw)
                out = str(raw.get("text") or "")
            else:
                response = await self._chat(
                    {
                        "model": settings.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": max_tokens},
                    }
                )
                self._record_usage(response)
                out = self._message_text(response)
            if settings.llm_cache:
                self._cache[cache_key] = {"text": out}
            return out
        except Exception as exc:  # noqa: BLE001
            logger.error("llm text call failed: %s — using fallback", redact_secrets(str(exc)))
            self.fallback_count += 1
            return fallback()


llm = LLMClient()
