"""Ollama first, OpenAI second, deterministic fallback last — and never a crash.

The ordering is the contract: the local model costs nothing and sends nothing
off the machine, so it is always asked first. OpenAI is a second chance before
the deterministic fallback, never a replacement for it.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.llm.client import LLMClient
from app.llm.tools import CHOOSE_EXECUTOR


@pytest.fixture
def client(monkeypatch):
    """A client with caching off, so each test really makes its call."""
    monkeypatch.setattr(settings, "llm_cache", False)
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    return LLMClient()


def _dead_ollama(monkeypatch):
    def boom(payload):
        raise RuntimeError("ollama is not running")

    monkeypatch.setattr(LLMClient, "_ollama_chat", staticmethod(boom))


def _canned_openai(monkeypatch, content: str):
    def respond(payload):
        assert payload["messages"], "the prompt must reach the fallback provider"
        return {
            "message": {"content": content},
            "prompt_eval_count": 11,
            "eval_count": 7,
            "_provider": "openai",
        }

    monkeypatch.setattr(LLMClient, "_openai_chat", staticmethod(respond))


async def test_openai_answers_when_ollama_is_down(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    _dead_ollama(monkeypatch)
    _canned_openai(
        monkeypatch,
        '{"method": "playwright", "rationale": "from openai", "confidence": 0.8}',
    )

    result = await client.structured(
        prompt="choose a runtime",
        tool=CHOOSE_EXECUTOR,
        fallback=lambda: {"method": "python", "rationale": "deterministic"},
    )
    assert result["method"] == "playwright"
    assert client.fallback_count == 0, "the deterministic path must not have run"


async def test_without_a_key_a_dead_ollama_goes_deterministic(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    _dead_ollama(monkeypatch)

    result = await client.structured(
        prompt="choose a runtime",
        tool=CHOOSE_EXECUTOR,
        fallback=lambda: {"method": "python", "rationale": "deterministic"},
    )
    assert result["rationale"] == "deterministic"
    assert client.fallback_count == 1


async def test_both_providers_failing_still_returns_the_fallback(client, monkeypatch):
    """The whole point: a provider outage degrades output, it never raises."""
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    _dead_ollama(monkeypatch)

    def also_boom(payload):
        raise RuntimeError("openai is unreachable too")

    monkeypatch.setattr(LLMClient, "_openai_chat", staticmethod(also_boom))

    result = await client.structured(
        prompt="choose a runtime",
        tool=CHOOSE_EXECUTOR,
        fallback=lambda: {"method": "python", "rationale": "deterministic"},
    )
    assert result["rationale"] == "deterministic"


async def test_ollama_is_preferred_when_it_works(client, monkeypatch):
    """A configured key must not divert work off the machine unnecessarily."""
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(
        LLMClient,
        "_ollama_chat",
        staticmethod(
            lambda payload: {
                "message": {"content": '{"method": "n8n", "rationale": "local", "confidence": 1}'},
                "prompt_eval_count": 3,
                "eval_count": 2,
            }
        ),
    )

    def must_not_run(payload):
        raise AssertionError("openai was called while ollama was healthy")

    monkeypatch.setattr(LLMClient, "_openai_chat", staticmethod(must_not_run))

    result = await client.structured(
        prompt="choose a runtime",
        tool=CHOOSE_EXECUTOR,
        fallback=lambda: {"method": "python"},
    )
    assert result["rationale"] == "local"


def test_the_openai_payload_translation_keeps_what_matters(monkeypatch):
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    translated = LLMClient._to_openai(
        {
            "model": "qwen2.5:1.5b-instruct",
            "messages": [{"role": "user", "content": "hello"}],
            "format": {"type": "object"},
            "options": {"temperature": 0, "num_predict": 400},
        }
    )
    assert translated["model"] == "gpt-4o-mini"
    assert translated["max_tokens"] == 400
    assert translated["response_format"] == {"type": "json_object"}
    assert translated["messages"][0]["content"] == "hello"


def test_images_become_openai_content_blocks(monkeypatch):
    """Vision has to survive the translation too, or screen reading breaks."""
    translated = LLMClient._to_openai(
        {
            "messages": [{"role": "user", "content": "what is this", "images": ["QUJD"]}],
            "options": {},
        }
    )
    blocks = translated["messages"][0]["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,QUJD")


def test_health_names_the_standby_provider(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    assert "fallback openai:gpt-4o-mini" in settings.llm_description

    monkeypatch.setattr(settings, "openai_api_key", "")
    assert "openai" not in settings.llm_description


def test_local_model_defaults_to_qwen3_8b():
    """The primary local model is qwen3:8b, and it is a plain configurable field.

    A regression here means either the default drifted or someone hardcoded a
    model name somewhere the env can no longer override.
    """
    from app.config import Settings

    assert Settings.model_fields["llm_model"].default == "qwen3:8b"
    assert Settings.model_fields["openai_model"].default == "gpt-4o-mini"


async def test_low_occurrence_alone_does_not_divert_work_to_openai(client, monkeypatch):
    """Demo mode is about the discovery floor, not about which provider answers.

    A small occurrence count must not push a call to OpenAI; the local model is
    still asked first. This guards the $10 budget against being spent simply
    because the demo is deliberately small.
    """
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "discovery_mode", "demo")
    monkeypatch.setattr(
        LLMClient,
        "_ollama_chat",
        staticmethod(
            lambda payload: {
                "message": {
                    "content": '{"method": "python", "rationale": "local", "confidence": 1}'
                },
                "prompt_eval_count": 3,
                "eval_count": 2,
            }
        ),
    )

    def must_not_run(payload):
        raise AssertionError("openai was called for a low-occurrence demo candidate")

    monkeypatch.setattr(LLMClient, "_openai_chat", staticmethod(must_not_run))

    result = await client.structured(
        prompt="choose a runtime",
        tool=CHOOSE_EXECUTOR,
        fallback=lambda: {"method": "n8n"},
    )
    assert result["rationale"] == "local"
