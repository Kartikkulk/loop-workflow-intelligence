"""Gemini provider tests. Mocked SDK only — no live Gemini API calls."""

from __future__ import annotations

import json
import logging

import pytest

from app.config import settings
from app.llm.client import LLMClient, redact_secrets
from app.llm.tools import INVESTIGATE_WORKFLOW


@pytest.fixture
def gemini_settings():
    orig = (
        settings.llm_provider,
        settings.llm_model,
        settings.gemini_api_key,
        settings.llm_cache,
        settings.llm_max_retries,
    )
    settings.llm_provider = "gemini"
    settings.llm_model = "gemini-2.5-flash"
    settings.gemini_api_key = "test-not-a-real-key"
    settings.llm_cache = False
    settings.llm_max_retries = 2
    yield
    (
        settings.llm_provider,
        settings.llm_model,
        settings.gemini_api_key,
        settings.llm_cache,
        settings.llm_max_retries,
    ) = orig


def test_gemini_provider_selection(gemini_settings):
    assert settings.has_llm is True
    client = LLMClient()
    assert client.available is True


def test_missing_api_key_is_unavailable():
    orig = (settings.llm_provider, settings.gemini_api_key, settings.llm_model)
    settings.llm_provider = "gemini"
    settings.llm_model = "gemini-2.5-flash"
    settings.gemini_api_key = ""
    try:
        assert settings.has_llm is False
        assert LLMClient().available is False
    finally:
        settings.llm_provider, settings.gemini_api_key, settings.llm_model = orig


@pytest.mark.asyncio
async def test_missing_api_key_uses_fallback():
    orig = (settings.llm_provider, settings.gemini_api_key, settings.llm_model, settings.llm_cache)
    settings.llm_provider = "gemini"
    settings.llm_model = "gemini-2.5-flash"
    settings.gemini_api_key = "   "
    settings.llm_cache = False
    client = LLMClient()
    try:
        result = await client.structured(
            prompt="investigate",
            tool=INVESTIGATE_WORKFLOW,
            fallback=lambda: {"conclusions": [], "final_decision": "insufficient_evidence"},
        )
        assert result["final_decision"] == "insufficient_evidence"
        assert client.fallback_count == 1
        assert client.call_count == 0
    finally:
        (
            settings.llm_provider,
            settings.gemini_api_key,
            settings.llm_model,
            settings.llm_cache,
        ) = orig


@pytest.mark.asyncio
async def test_gemini_structured_output_parsing(gemini_settings):
    payload = {
        "conclusions": [
            {
                "relationship": "conditional_step",
                "confidence": 0.81,
                "evidence_ids": ["variant_stats_01"],
            }
        ],
        "semantic_relationships": [],
        "evidence_gaps": [],
        "investigation_notes": ["parsed"],
        "final_decision": "safe_to_continue",
    }
    client = LLMClient()

    def fake_generate(*, prompt, schema, max_tokens):
        assert "type" in schema
        assert prompt
        return {
            "text": json.dumps(payload),
            "parsed": payload,
            "prompt_eval_count": 11,
            "eval_count": 7,
        }

    client._gemini_generate_content = fake_generate  # type: ignore[method-assign]
    result = await client.structured(
        prompt="packet",
        tool=INVESTIGATE_WORKFLOW,
        fallback=lambda: {"failed": True},
    )
    assert result["final_decision"] == "safe_to_continue"
    assert result["conclusions"][0]["relationship"] == "conditional_step"
    assert client.call_count == 1
    assert client.fallback_count == 0


@pytest.mark.asyncio
async def test_gemini_structured_parses_text_when_parsed_missing(gemini_settings):
    payload = {
        "conclusions": [],
        "semantic_relationships": [],
        "evidence_gaps": ["thin"],
        "investigation_notes": [],
        "final_decision": "insufficient_evidence",
    }
    client = LLMClient()

    def fake_generate(*, prompt, schema, max_tokens):
        return {
            "text": json.dumps(payload),
            "parsed": None,
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    client._gemini_generate_content = fake_generate  # type: ignore[method-assign]
    result = await client.structured(
        prompt="packet",
        tool=INVESTIGATE_WORKFLOW,
        fallback=lambda: {"failed": True},
    )
    assert result["final_decision"] == "insufficient_evidence"
    assert "failed" not in result


@pytest.mark.asyncio
async def test_gemini_api_error_uses_fallback(gemini_settings, caplog):
    client = LLMClient()

    def boom(*, prompt, schema, max_tokens):
        raise RuntimeError("401 API_KEY_INVALID AIzaSySECRETVALUE99 key=AIzaSySECRETVALUE99")

    client._gemini_generate_content = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="loop.llm"):
        result = await client.structured(
            prompt="packet",
            tool=INVESTIGATE_WORKFLOW,
            fallback=lambda: {"conclusions": [], "final_decision": "insufficient_evidence"},
        )
    assert result["final_decision"] == "insufficient_evidence"
    assert client.fallback_count == 1
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "AIzaSySECRETVALUE99" not in joined
    assert "[redacted]" in joined


def test_redact_secrets_strips_gemini_key(gemini_settings):
    settings.gemini_api_key = "super-secret-demo-token"
    raw = "failed with super-secret-demo-token in the request"
    assert "super-secret-demo-token" not in redact_secrets(raw)


@pytest.mark.asyncio
async def test_ollama_path_unchanged_when_provider_is_ollama():
    orig = (settings.llm_provider, settings.llm_model, settings.llm_cache)
    settings.llm_provider = "ollama"
    settings.llm_model = "qwen2.5:1.5b-instruct"
    settings.llm_cache = False
    client = LLMClient()
    called = {"gemini": 0}

    def should_not_run(*, prompt, schema, max_tokens):
        called["gemini"] += 1
        raise AssertionError("Gemini must not be called for ollama provider")

    client._gemini_generate_content = should_not_run  # type: ignore[method-assign]

    def fake_ollama(payload):
        return {
            "message": {
                "content": json.dumps(
                    {
                        "conclusions": [],
                        "semantic_relationships": [],
                        "evidence_gaps": [],
                        "investigation_notes": ["ollama"],
                        "final_decision": "insufficient_evidence",
                    }
                )
            },
            "prompt_eval_count": 3,
            "eval_count": 2,
        }

    client._ollama_chat = fake_ollama  # type: ignore[method-assign]
    try:
        result = await client.structured(
            prompt="packet",
            tool=INVESTIGATE_WORKFLOW,
            fallback=lambda: {"failed": True},
        )
        assert called["gemini"] == 0
        assert result["investigation_notes"] == ["ollama"]
        assert client.fallback_count == 0
    finally:
        settings.llm_provider, settings.llm_model, settings.llm_cache = orig
