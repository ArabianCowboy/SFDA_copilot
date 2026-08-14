"""Changing the model, without tearing an answer in half.

This is the only phase that touches the answer path, and the property being
defended is narrow: a handler is either wholly the old one or wholly the new
one. The model, the token ceiling, the temperature and the tokenizer are
established together in the constructor, so replacing the object is the only
way to change one of them without a window in which two of them disagree.

Everything here exists to prove that window does not exist.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from web.api.app import create_app
from web.services.audit import AuditActor
from web.services.openai_app import OpenAIHandler
from web.services.result_combiner import SearchResult


ADMIN = {"Authorization": "Bearer fake_admin_token"}

# Settings writes now carry who made them, because the change and its audit
# row are written together — there is no way to store one without the other.
ACTOR = AuditActor("admin-id", "admin@example.com", "127.0.0.1", "pytest")
AUTH = {"Authorization": "Bearer fake_token"}


@pytest.fixture
def app():
    application = create_app(testing=True)
    application.config["search_engine"].search.return_value = [
        SearchResult(
            text="Chunk about registration requirements.",
            score=0.71,
            document="Guidance.pdf",
            category="regulatory",
            page=14,
            chunk_id="c1",
            metadata={"semantic_score": 0.6, "lexical_score": 0.8},
        )
    ]
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _meta_model(raw: str) -> str:
    """The model named in the SSE meta frame."""
    import json

    for line in raw.splitlines():
        if line.startswith("data:") and '"model"' in line:
            return json.loads(line[len("data:"):].strip())["model"]
    raise AssertionError("no meta frame in the stream")


# ── Replacement, not mutation ─────────────────────────────────────────────────


def test_applying_settings_replaces_the_handler_object(app):
    """Mutation is what this design exists to avoid.

    Four attributes reassigned one at a time can be observed half-applied by
    one of the eight threads — a new model against an old token ceiling — and
    the tokenizer is bound to the model at construction, so a naive
    `handler.model = x` leaves those two disagreeing silently.
    """
    with app.app_context():
        before = app.config["openai_handler"]
        app.config["settings_service"].update({"model": "gpt-4o"}, actor=ACTOR)
        app.config["apply_generation_settings"]()
        after = app.config["openai_handler"]

    assert after is not before
    assert after.model == "gpt-4o"
    assert before.model == "gpt-4o-mini", "the old handler must not be touched"


def test_a_reference_captured_before_the_swap_is_unaffected(app):
    """What a request holds. Each view captures the handler once at the top and
    its generator closes over that local, so this is the mechanism by which an
    in-flight answer survives a settings change."""
    with app.app_context():
        captured = app.config["openai_handler"]
        app.config["settings_service"].update({"model": "gpt-4o"}, actor=ACTOR)
        app.config["apply_generation_settings"]()

    assert captured.model == "gpt-4o-mini"


def test_a_handler_that_will_not_build_leaves_the_running_one_in_place(app):
    """A bad setting must not be able to take the chatbot down."""
    with app.app_context():
        original = app.config["openai_handler"]

        def explode(settings=None):
            raise RuntimeError("bad model")

        app.config["openai_handler_factory"] = explode
        applied = app.config["apply_generation_settings"]()

        assert applied is False
        assert app.config["openai_handler"] is original


# ── What the reader is told ───────────────────────────────────────────────────


def test_the_meta_frame_names_the_model_that_answered(client):
    """The frame exists to disclose which model produced the answer.

    `handler` is captured once in the view body and the generator closes over
    it, so the frame and the generation call read the same object — they cannot
    disagree even if a swap lands between them.
    """
    response = client.post(
        "/api/chat/stream", json={"query": "registration?", "category": "all"}, headers=AUTH
    )
    assert _meta_model(response.get_data(as_text=True)) == "gpt-4o-mini"


def test_a_model_change_shows_up_on_the_next_answer(client, app):
    client.put("/admin/api/settings", json={"model": "gpt-4o"}, headers=ADMIN)

    response = client.post(
        "/api/chat/stream", json={"query": "registration?", "category": "all"}, headers=AUTH
    )
    assert _meta_model(response.get_data(as_text=True)) == "gpt-4o"


def test_a_stream_already_running_finishes_on_its_own_handler(client, app):
    """The tear this whole design exists to prevent.

    The request is started, the meta frame read, and only then is the handler
    swapped — genuinely mid-generation, which is verifiable: the first chunk is
    the meta frame alone and thousands of bytes follow it.

    The replacement is given a *different answer* so the two handlers are
    distinguishable in the output. If the running request picked up the new
    handler, the reader would be told one model in the meta frame and served
    another — the exact dishonesty the frame exists to prevent.
    """
    original = app.config["openai_handler"]
    original.stream_response.side_effect = lambda *a, **k: iter(["ANSWER-FROM-ORIGINAL"])

    response = client.post(
        "/api/chat/stream", json={"query": "registration?", "category": "all"}, headers=AUTH
    )
    stream = response.iter_encoded()

    first = next(stream).decode()
    assert "gpt-4o-mini" in first, "the meta frame should arrive first, alone"
    assert "event: done" not in first, "the stream must still be open for this to mean anything"

    # Swap underneath the running generator, with a visibly different answer.
    replacement = MagicMock(spec=OpenAIHandler)
    replacement.model = "gpt-4o"
    replacement.max_context_results = original.max_context_results
    replacement.stream_response.side_effect = lambda *a, **k: iter(["ANSWER-FROM-REPLACEMENT"])
    replacement.generate_suggestions.return_value = []
    app.config["openai_handler"] = replacement

    rest = b"".join(stream).decode()

    assert "ANSWER-FROM-ORIGINAL" in rest
    assert "ANSWER-FROM-REPLACEMENT" not in rest
    assert "event: done" in rest
    # And the swap did take effect for whoever comes next.
    assert app.config["openai_handler"] is replacement


# ── Persistence across a restart ──────────────────────────────────────────────


def test_stored_overrides_are_adopted_at_startup(app):
    """A model chosen in the console must survive a restart, or an operator
    fixes a degraded model at 2am and loses it on the next deploy."""
    with app.app_context():
        app.config["settings_service"].update({"model": "gpt-4o"}, actor=ACTOR)
        stored = app.config["admin_backend"]().get_settings()

    assert stored == {"model": "gpt-4o"}

    # A fresh app sharing that store: this is what a restart looks like.
    restarted = create_app(testing=True)
    restarted.config["_testing_admin_backend"].put_settings(
        stored, actor=ACTOR, before={}, after=stored
    )
    with restarted.app_context():
        restarted.config["settings_service"].snapshot(force=True)
        restarted.config["apply_generation_settings"]()
        assert restarted.config["openai_handler"].model == "gpt-4o"


# ── The tokenizer, which is the invariant a mutation would break ─────────────


def test_the_tokenizer_is_built_with_the_model(monkeypatch):
    """They are established together or not at all.

    A handler whose tokenizer belongs to a different model than its `model`
    attribute reports token counts for text it never encoded that way — and
    nothing would say so.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    handler = OpenAIHandler({"model": "gpt-4o"})

    assert handler.model == "gpt-4o"
    assert handler.tokenizer_exact is True
    assert handler.tokenizer.name == OpenAIHandler({"model": "gpt-4o"}).tokenizer.name


def test_a_model_tiktoken_does_not_know_falls_back_loudly(monkeypatch, caplog):
    """Refusing outright would mean this app could not be pointed at a model
    newer than the installed tiktoken. Falling back silently would mean token
    counts quietly stop meaning anything, so the flag records it."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with caplog.at_level("WARNING"):
        handler = OpenAIHandler({"model": "a-model-from-the-future"})

    assert handler.tokenizer_exact is False
    assert handler.tokenizer is not None
    assert "a-model-from-the-future" in caplog.text


def test_overrides_do_not_leak_between_handlers(monkeypatch):
    """Each handler owns its own settings; building one must not touch another."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    default = OpenAIHandler()
    overridden = OpenAIHandler({"model": "gpt-4o", "temperature": 0.9})

    assert default.model == "gpt-4o-mini"
    assert default.temperature != 0.9
    assert overridden.temperature == 0.9


def test_the_citation_clamp_survives_an_override(monkeypatch):
    """retrieved[i] must be the same passage as prompt block [i].

    An operator asking for more passages than the retriever returns would
    otherwise produce citation numbers for passages the model never saw.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    handler = OpenAIHandler({"max_context_results": 500})

    from web.utils.config_loader import config
    assert handler.max_context_results == config.get("search_engine", "k", 8)
