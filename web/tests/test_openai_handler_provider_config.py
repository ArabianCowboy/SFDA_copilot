"""Tests for OpenAIHandler's harness-only provider overrides.

``base_url``, ``api_key_env`` and ``model_contract`` exist so the
citation-fidelity harness (``scripts/eval_citations.py``) can call a
non-OpenAI provider through the real ``_build_messages``/``_prepare_context``/
``BASE_SYSTEM_MESSAGE`` prompt-assembly path, instead of a reimplementation
that risks drifting from what production actually sends.

No production caller sets any of the three today — ``config.yaml``'s
``allowed_models`` has no such fields, and ``settings_service.py``'s
``GENERATION_KEYS`` does not accept them from the console — so the load-
bearing property under test is that omitting them behaves EXACTLY as before.
That property, not the new fields themselves, is what an adversarial review
of this change specifically asked to be tested: the reader-facing app
constructs ``OpenAIHandler()`` at normal startup (``web/api/app.py``) and
again on every settings change (``apply_generation_settings``), so a mistake
here is not confined to the harness.
"""

from __future__ import annotations

import pytest

from web.services.openai_app import OpenAIHandler


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-default")


def test_omitted_settings_use_the_openai_sdk_default_base_url():
    """No override at all — today's exact production shape."""
    handler = OpenAIHandler()
    assert handler.client.base_url is not None  # the SDK's own public endpoint
    assert str(handler.client.base_url).startswith("https://api.openai.com")
    assert handler._model_contract_override is None


def test_omitted_settings_read_the_default_api_key_env():
    handler = OpenAIHandler()
    assert handler.client.api_key == "sk-test-default"


def test_explicit_base_url_is_honored():
    handler = OpenAIHandler({"base_url": "https://api.deepseek.com"})
    assert str(handler.client.base_url).rstrip("/") == "https://api.deepseek.com"


def test_explicit_api_key_env_reads_the_named_variable(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    handler = OpenAIHandler({"api_key_env": "DEEPSEEK_API_KEY"})
    assert handler.client.api_key == "sk-deepseek-test"


def test_missing_named_key_raises_with_the_right_variable_name(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        OpenAIHandler({"api_key_env": "DEEPSEEK_API_KEY"})


def test_settings_normalization_happens_before_client_construction():
    """The bug an adversarial review caught before it shipped: building the
    client before `settings = settings or {}` ran meant `settings.get(...)`
    on a `None` settings argument raised AttributeError. This is the
    regression test for that ordering, not just for the feature."""
    # No settings argument at all — the exact call every production site makes.
    OpenAIHandler()  # must not raise


def test_model_contract_override_is_used_instead_of_the_allowlist_lookup():
    """A harness candidate model, absent from config.yaml's allowed_models,
    must get ITS declared contract, not the conservative default one."""
    handler = OpenAIHandler(
        {
            "model": "deepseek-v4-flash",
            "model_contract": {
                "token_param": "max_completion_tokens",
                "supports_temperature": False,
                "reasoning_efforts": [],
            },
        }
    )
    kwargs = handler._request_kwargs(1000, 0.2)
    assert "max_completion_tokens" in kwargs
    assert "max_tokens" not in kwargs
    assert "temperature" not in kwargs


def test_no_model_contract_override_falls_back_to_the_allowlist_lookup():
    """Every production model, unchanged: model_spec(self.model) still decides."""
    handler = OpenAIHandler({"model": "gpt-4o-mini"})
    kwargs = handler._request_kwargs(1000, 0.2)
    assert kwargs["max_tokens"] == 1000
    assert kwargs["temperature"] == 0.2


def test_a_failed_provider_construction_raises_rather_than_silently_degrading():
    """apply_generation_settings (web/api/app.py) relies on the factory call
    raising so it can keep the running handler instead of swapping in a
    broken one — see that function's own docstring. A missing key must still
    raise, whatever base_url/api_key_env combination was requested."""
    import os

    key_env = "SOME_PROVIDER_KEY_NOT_SET"
    os.environ.pop(key_env, None)
    with pytest.raises(ValueError):
        OpenAIHandler({"api_key_env": key_env, "base_url": "https://example.invalid/v1"})
