"""How the provider's ``finish_reason`` gets out of ``stream_response``.

The handler is ONE instance shared by every request thread
(``--workers 1 --threads 8``) and is documented as immutable after
construction — ``apply_generation_settings`` builds a replacement and rebinds
``app.config["openai_handler"]`` rather than mutating the live one. So the
terminal reason cannot ride on ``self``: it would be read by whichever request
wrote it last, and a truncation warning under the wrong answer is worse than no
warning at all.

It rides a caller-allocated ``FinishSignal`` instead. These tests pin the
mechanism, the placement inside the chunk loop, and the immutability that made
both necessary.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from web.services.openai_app import FinishSignal, OpenAIHandler


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-default")


def chunk(content=None, finish_reason=None, *, choices=True):
    """One streaming chunk, shaped like the SDK's ChatCompletionChunk.

    ``choices=False`` is the usage-only final chunk that arrives when
    ``stream_options={"include_usage": True}`` is set: the SDK documents its
    ``choices`` as always an empty list, which is what the loop's first guard
    exists for.
    """
    if not choices:
        return SimpleNamespace(choices=[])
    return SimpleNamespace(
        choices=[
            SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish_reason)
        ]
    )


def fake_stream(handler, chunks):
    """Replace only the upstream call, keeping the real loop under test."""

    class _Stream:
        def __enter__(self):
            return iter(chunks)

        def __exit__(self, *exc):
            return False

    handler.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: _Stream()))
    )


def drain(handler, sink=None):
    return "".join(handler.stream_response("a question", [], finish=sink))


def test_the_sink_records_a_length_truncation():
    """The whole point: `length` must be observable by the caller."""
    handler = OpenAIHandler()
    # The reason arrives on a chunk whose delta.content is None — verified
    # against the installed SDK, where ChoiceDelta.content is Optional[str].
    fake_stream(handler, [chunk("Applications "), chunk(None, "length")])
    sink = FinishSignal()

    text = drain(handler, sink)

    assert text == "Applications "
    assert sink.reason == "length"


def test_a_reason_on_a_content_bearing_chunk_is_still_recorded():
    """Some OpenAI-compatible gateways report it alongside the last token."""
    handler = OpenAIHandler()
    fake_stream(handler, [chunk("Applications ", None), chunk("must be [1].", "stop")])
    sink = FinishSignal()

    assert drain(handler, sink) == "Applications must be [1]."
    assert sink.reason == "stop"


def test_a_provider_that_reports_nothing_leaves_the_sink_empty():
    """None is NOT "stop" — the route decides what to say about an absence.

    Pinning it here keeps that decision in one place. Defaulting inside the
    handler would hide a silent truncation behind a manufactured "stop".
    """
    handler = OpenAIHandler()
    fake_stream(handler, [chunk("An answer.")])
    sink = FinishSignal()

    drain(handler, sink)

    assert sink.reason is None


def test_the_usage_only_final_chunk_does_not_crash_the_loop():
    """`include_usage` sends a last chunk whose `choices` is an empty list."""
    handler = OpenAIHandler()
    fake_stream(handler, [chunk("An answer.", "stop"), chunk(choices=False)])
    sink = FinishSignal()

    assert drain(handler, sink) == "An answer."
    assert sink.reason == "stop"


def test_the_sink_is_optional():
    """Positional callers — scripts/eval_citations.py, smoke_real.py — are unaffected."""
    handler = OpenAIHandler()
    fake_stream(handler, [chunk("An answer.", "length")])

    assert drain(handler) == "An answer."


def test_the_handler_stores_no_finish_state_of_its_own():
    """The immutability contract, as an assertion rather than a comment.

    Two interleaved streams on ONE handler — the production shape, eight threads
    to one instance — must not see each other's terminal reason.
    """
    handler = OpenAIHandler()
    before = set(vars(handler))

    fake_stream(handler, [chunk("First.", "length")])
    first = FinishSignal()
    drain(handler, first)

    fake_stream(handler, [chunk("Second.", "stop")])
    second = FinishSignal()
    drain(handler, second)

    assert (first.reason, second.reason) == ("length", "stop")
    # Nothing new latched onto the shared instance along the way.
    assert set(vars(handler)) == before


def test_the_easter_egg_reports_stop_explicitly():
    """It never calls a provider, and a whole answer must not read as unknown."""
    from web.services.openai_app import EASTER_EGG_QUERY

    handler = OpenAIHandler()
    sink = FinishSignal()

    list(handler.stream_response(EASTER_EGG_QUERY, [], finish=sink))

    assert sink.reason == "stop"
