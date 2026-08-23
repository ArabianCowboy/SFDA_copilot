"""Conversation history, held outside the Flask session cookie.

Why this exists
---------------
Flask writes ``Set-Cookie`` in ``finalize_request()``, which runs after the
view returns the Response object but *before* the WSGI server iterates the
body. So a ``session["chat_history"] = ...`` executed inside a streaming
generator is silently discarded — no error, history just stops persisting and
multi-turn context quietly dies.

The fix is to keep only an opaque conversation id in the cookie and hold the
turns here. The view reads/writes the session; the generator only touches this
store.

Scope
-----
PROCESS-LOCAL. Running more than one worker would split conversations across
them. That is already the required deployment shape for this app — the FAISS
index and sentence-transformers model live in RAM — so gunicorn should run
``--workers 1 --threads 8``. Swapping the backing dict for Redis is the seam if
that ever changes.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict

logger = logging.getLogger(__name__)


class ConversationStore:
    """TTL + LRU bounded chat history keyed by (owner, conversation id).

    The owner half was added with durable persistence. Before it, a conversation
    id was reachable by anyone presenting it, which was safe only because the id
    could reach a browser exactly one way — the cookie that minted it — and
    `_bind_session_to_identity` purges that on any change of reader. Durable
    history breaks that assumption: an id now also arrives from the database
    (`chat_latest_session`), and Phase 2's deep links would let one arrive from
    a URL. Owner-keying means the window cannot be reached by presenting the id
    alone, whichever door the id came through.

    `owner_id` is keyword-only and defaults to None so the store's own unit
    tests can key on a bare id. Every request path passes a real owner, and
    `test_the_streaming_route_keys_history_by_owner` is what stops one being
    dropped.
    """

    def __init__(self, max_conversations: int = 500, ttl_seconds: int = 3600) -> None:
        self._data: OrderedDict[tuple[str | None, str], tuple[float, list[dict[str, str]]]] = (
            OrderedDict()
        )
        self._max = max_conversations
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    # Injected so tests can control time without patching module globals.
    @staticmethod
    def _now() -> float:
        import time

        return time.monotonic()

    def _evict(self) -> None:
        """Caller must hold the lock."""
        now = self._now()
        expired = [k for k, (stamp, _) in self._data.items() if now - stamp > self._ttl]
        for key in expired:
            del self._data[key]
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def get(self, conversation_id: str, *, owner_id: str | None = None) -> list[dict[str, str]]:
        """Return the turns for a conversation, newest last.

        Reading refreshes the TTL stamp, so the hour is one of INACTIVITY
        rather than one measured from the last successful write. The two only
        diverge when a turn is read but never appended — a retrieval outage, a
        model error, a cancelled stream — and there the write-based reading
        punishes the reader for the server's failure by expiring the history
        they were still using.
        """
        key = (owner_id, conversation_id)
        with self._lock:
            self._evict()
            entry = self._data.get(key)
            if entry is None:
                return []
            self._data[key] = (self._now(), entry[1])
            self._data.move_to_end(key)
            return list(entry[1])

    def append_turn(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        max_pairs: int,
        max_chars: int,
        *,
        owner_id: str | None = None,
    ) -> list[dict[str, str]]:
        """Record one exchange, then trim by pair count and serialized size."""
        key = (owner_id, conversation_id)
        with self._lock:
            _, history = self._data.get(key, (self._now(), []))
            history = list(history)
            history.extend(
                [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": assistant_message},
                ]
            )
            history = _truncate(history, max_pairs, max_chars)
            self._data[key] = (self._now(), history)
            self._data.move_to_end(key)
            # Evict AFTER inserting, or the size bound is only enforced on the
            # next call and the store can sit one over its cap indefinitely.
            self._evict()
            return history

    def adopt_cookie_history(
        self,
        conversation_id: str,
        cookie_history: list[dict[str, str]] | None,
        *,
        owner_id: str | None = None,
    ) -> None:
        """One-time migration of history that still lives in a session cookie.

        Without this, everyone mid-conversation at deploy time loses context.
        """
        if not cookie_history:
            return
        key = (owner_id, conversation_id)
        with self._lock:
            if key in self._data:
                return
            self._data[key] = (self._now(), list(cookie_history))
            logger.info(
                "Adopted %d cookie message(s) into the conversation store.", len(cookie_history)
            )

    def replace(
        self,
        conversation_id: str,
        history: list[dict[str, str]],
        max_pairs: int,
        max_chars: int,
        *,
        owner_id: str | None = None,
    ) -> list[dict[str, str]]:
        """Seed the window from durable rows. Returns what was actually kept.

        Trimmed through the same `_truncate` an append goes through, not stored
        raw. The loader's row limit bounds how many MESSAGES come back; it says
        nothing about their size, and a restored conversation of long Arabic
        answers would otherwise hand the model a prompt window several times the
        budget every other path is held to.

        A leading assistant message is dropped first. `_truncate` slices on a
        strict [user, assistant, …] alternation, and a row limit that lands on
        an odd boundary would hand it a window starting mid-exchange.

        IT REFUSES TO OVERWRITE A NON-EMPTY WINDOW, and that is the whole
        reason it is not a plain assignment. Hydration is a check-then-act
        across two calls — the caller reads an empty window, goes to Postgres,
        and comes back to install what it found — and the lock inside each
        method does not span the gap. Two threads on one conversation (two
        tabs, or a reload racing an in-flight question) both see it empty and
        both fetch history H. The first installs H and completes a turn, so the
        window is H+A; the second then arrives with its now-stale H and, with a
        plain assignment, would erase a turn the reader had already been shown.
        Losing to a concurrent writer is correct here: whatever is in the window
        is at least as fresh as anything a completed database read can hold.
        """
        history = list(history)
        if history and history[0].get("role") == "assistant":
            history = history[1:]
        history = _truncate(history, max_pairs, max_chars)
        key = (owner_id, conversation_id)
        with self._lock:
            existing = self._data.get(key)
            if existing is not None and existing[1]:
                return list(existing[1])
            self._data[key] = (self._now(), history)
            self._data.move_to_end(key)
            self._evict()
        return history

    def clear(self, conversation_id: str) -> None:
        """Drop this conversation for EVERY owner, not just one.

        Deliberately not owner-scoped, and this is the asymmetry that matters:
        `purge_conversation_state` calls it holding a cookie and an id but no
        guarantee about which owner the entry was filed under — the identity may
        already have rotated, or the entry may predate owner-keying in a process
        that is still running. Under-purging is a leak of one reader's questions
        into another's prompt, which is the exact incident
        test_session_isolation.py exists to pin. Over-purging costs a cache miss
        against an id that is a uuid and therefore belongs to one conversation
        anyway.
        """
        with self._lock:
            for key in [k for k in self._data if k[1] == conversation_id]:
                del self._data[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


ELISION_NOTICE = "\n\n[… the rest of this message is omitted from the conversation history …]"


def _clamp(message: dict[str, str], limit: int) -> dict[str, str]:
    """Cut one over-long message down to `limit` characters, visibly.

    A single message must never be large enough to price the whole exchange
    out of the budget — that is how one long answer used to take the entire
    conversation with it. Clamping bounds each message so the newest exchange
    always has room.

    The notice is not decoration. Handing the model a silently severed answer
    invites it to treat a truncated list as complete and contradict itself
    against what the reader can still see on screen; saying the text is
    partial costs a few tokens and removes that failure.

    The head is kept rather than the tail because these are RAG answers: the
    direct response leads and the elaboration follows.
    """
    content = message.get("content", "")
    if len(content) <= limit:
        return message
    head = max(0, limit - len(ELISION_NOTICE))
    return {**message, "content": content[:head] + ELISION_NOTICE}


def _truncate(
    history: list[dict[str, str]], max_pairs: int, max_chars: int
) -> list[dict[str, str]]:
    """Trim to max_pairs exchanges, then to max_chars of serialized JSON.

    THE NEWEST EXCHANGE ALWAYS SURVIVES. That invariant is the whole point of
    this function's shape, and its absence was a bug: the loop below used to
    run while `trimmed` was merely non-empty, so an exchange that exceeded the
    budget on its own was dropped by the very call that recorded it — taking
    every older turn with it and returning []. A four-turn conversation went
    0 -> 547 -> 205 -> 0 logged history tokens, and the model, asked what had
    been discussed, answered from nothing.

    So the budget is enforced in the only order that can hold that invariant:
    clamp each message first, then drop whole pairs oldest-first, and stop at
    one pair whether or not the budget is met. A lone clamped exchange can sit
    slightly over `max_chars` — bounded by the per-message limit below — and
    that is the deliberate trade. Exceeding a soft memory budget by one
    exchange is cheap; discarding the turn the reader is looking at is not.
    """
    # Half the budget, so a clamped pair lands near max_chars rather than at
    # twice it. This is what keeps the floor below from being unbounded.
    per_message = max_chars // 2
    trimmed = [_clamp(m, per_message) for m in history[-(max_pairs * 2) :]]
    # ensure_ascii=False: the default True escapes every non-ASCII character
    # (e.g. Arabic) to a 6-char \uXXXX sequence, so a ~950-char Arabic
    # exchange would measure ~4,700 chars against a 3,500 budget and the loop
    # below would drop it to nothing. Pinned by
    # test_store_measures_serialized_size_without_ascii_escaping and
    # test_arabic_history_survives_the_blocking_path.
    while len(trimmed) > 2 and len(json.dumps(trimmed, ensure_ascii=False)) > max_chars:
        trimmed = trimmed[2:]  # drop the oldest user/assistant pair
    return trimmed
