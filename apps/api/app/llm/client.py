"""Local LLM wrapper: retry with backoff, prompt-hash cache, safe fallback.

Every call site must supply a `fallback` callable. When the local model is not
running — or the API fails after all retries — the fallback runs instead. This
keeps the whole product demonstrable offline and means a runtime problem on stage
degrades output quality rather than breaking the demo.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
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


class LLMClient:
    """Thin, dependency-injectable local LLM client."""

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
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"ollama returned HTTP {exc.code}: {detail}") from exc

    @staticmethod
    def _to_openai(payload: dict[str, Any]) -> dict[str, Any]:
        """Translate an Ollama chat payload into an OpenAI one.

        Only the fields this client actually sends are translated; anything the
        callers do not use is not invented here. JSON-schema output becomes
        `json_object` mode rather than OpenAI's strict `json_schema`, because
        strict mode rejects a schema that does not set `additionalProperties`
        false on every level, and the schemas here are shared with Ollama.
        The schema is already in the prompt, so the model still sees it.
        """
        messages: list[dict[str, Any]] = []
        for message in payload.get("messages") or []:
            images = message.get("images") or []
            if not images:
                messages.append(
                    {"role": message.get("role", "user"), "content": message.get("content", "")}
                )
                continue
            blocks: list[dict[str, Any]] = [
                {"type": "text", "text": message.get("content", "")}
            ]
            blocks.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image}"},
                }
                for image in images
            )
            messages.append({"role": message.get("role", "user"), "content": blocks})

        options = payload.get("options") or {}
        translated: dict[str, Any] = {
            "model": settings.openai_model,
            "messages": messages,
            "temperature": options.get("temperature", 0),
        }
        if options.get("num_predict"):
            translated["max_tokens"] = int(options["num_predict"])
        if payload.get("format"):
            translated["response_format"] = {"type": "json_object"}
        return translated

    @staticmethod
    def _openai_chat(payload: dict[str, Any]) -> dict[str, Any]:
        """Call OpenAI and return the response in Ollama's shape.

        Normalising here rather than at the call sites is what keeps the
        fallback invisible: `structured`, `text` and `structured_multimodal`
        read `message.content` and the token counts either way, so none of them
        needed a branch for this.
        """
        url = settings.openai_base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(LLMClient._to_openai(payload)).encode()
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.openai_api_key.strip()}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"openai returned HTTP {exc.code}: {detail}") from exc

        choices = raw.get("choices") or []
        content = ""
        if choices:
            content = str((choices[0].get("message") or {}).get("content") or "")
        usage = raw.get("usage") or {}
        return {
            "message": {"content": content},
            "prompt_eval_count": int(usage.get("prompt_tokens") or 0),
            "eval_count": int(usage.get("completion_tokens") or 0),
            "_provider": "openai",
        }

    async def _chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Ask the local model; fall back to OpenAI when it cannot answer.

        The order is deliberate and not a preference about quality: the local
        model costs nothing and sends nothing off the machine, so it is asked
        first every time. OpenAI is a second chance before the deterministic
        fallback, not a replacement for it — with no key set, behaviour is
        exactly what it was.
        """
        local_error: Exception | None = None
        if settings.llm_provider.strip().lower() == "ollama" and settings.llm_model.strip():
            try:
                return await asyncio.to_thread(self._ollama_chat, payload)
            except Exception as exc:  # noqa: BLE001 — a second provider may still answer
                local_error = exc
                if not settings.has_openai_fallback:
                    raise
                logger.warning("ollama call failed (%s) — trying openai", exc)

        if not settings.has_openai_fallback:
            raise local_error or RuntimeError("no LLM provider is configured")

        response = await asyncio.to_thread(self._openai_chat, payload)
        logger.info("llm call served by openai model=%s", settings.openai_model)
        return response

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

    async def structured(
        self,
        *,
        prompt: str,
        tool: dict[str, Any],
        fallback: Callable[[], dict[str, Any]],
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Get a structured object out of the model via JSON-schema output.

        Ollama receives the same schema the old tool-use path used. The model's
        response is still parsed defensively, and any failure falls back.
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
                schema = dict(tool["input_schema"])
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
                served_by = str(response.get("_provider") or "ollama")
                logger.info(
                    "llm call ok provider=%s model=%s tool=%s in=%d out=%d",
                    served_by,
                    settings.openai_model if served_by == "openai" else settings.llm_model,
                    tool["name"],
                    int(response.get("prompt_eval_count") or 0),
                    int(response.get("eval_count") or 0),
                )
                result = json.loads(self._message_text(response))
                if not isinstance(result, dict):
                    raise ValueError("model returned a non-object JSON value")
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
            logger.error("llm text call failed: %s — using fallback", exc)
            self.fallback_count += 1
            return fallback()


llm = LLMClient()
