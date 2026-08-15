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
from typing import Any

logger = logging.getLogger(__name__)


class ConversationStore:
    """TTL + LRU bounded chat history keyed by an opaque conversation id."""

    def __init__(self, max_conversations: int = 500, ttl_seconds: int = 3600) -> None:
        self._data: OrderedDict[str, tuple[float, list[dict[str, str]]]] = OrderedDict()
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

    def get(self, conversation_id: str) -> list[dict[str, str]]:
        """Return the turns for a conversation, newest last.

        Reading refreshes the TTL stamp, so the hour is one of INACTIVITY
        rather than one measured from the last successful write. The two only
        diverge when a turn is read but never appended — a retrieval outage, a
        model error, a cancelled stream — and there the write-based reading
        punishes the reader for the server's failure by expiring the history
        they were still using.
        """
        with self._lock:
            self._evict()
            entry = self._data.get(conversation_id)
            if entry is None:
                return []
            self._data[conversation_id] = (self._now(), entry[1])
            self._data.move_to_end(conversation_id)
            return list(entry[1])

    def append_turn(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        max_pairs: int,
        max_chars: int,
    ) -> list[dict[str, str]]:
        """Record one exchange, then trim by pair count and serialized size."""
        with self._lock:
            _, history = self._data.get(conversation_id, (self._now(), []))
            history = list(history)
            history.extend(
                [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": assistant_message},
                ]
            )
            history = _truncate(history, max_pairs, max_chars)
            self._data[conversation_id] = (self._now(), history)
            self._data.move_to_end(conversation_id)
            # Evict AFTER inserting, or the size bound is only enforced on the
            # next call and the store can sit one over its cap indefinitely.
            self._evict()
            return history

    def adopt_cookie_history(
        self, conversation_id: str, cookie_history: list[dict[str, str]] | None
    ) -> None:
        """One-time migration of history that still lives in a session cookie.

        Without this, everyone mid-conversation at deploy time loses context.
        """
        if not cookie_history:
            return
        with self._lock:
            if conversation_id in self._data:
                return
            self._data[conversation_id] = (self._now(), list(cookie_history))
            logger.info("Adopted %d cookie message(s) into the conversation store.", len(cookie_history))

    def clear(self, conversation_id: str) -> None:
        with self._lock:
            self._data.pop(conversation_id, None)

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


def _truncate(history: list[dict[str, str]], max_pairs: int, max_chars: int) -> list[dict[str, str]]:
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
    trimmed = [_clamp(m, per_message) for m in history[-(max_pairs * 2):]]
    # ensure_ascii=False: the default True escapes every non-ASCII character
    # (e.g. Arabic) to a 6-char \uXXXX sequence, so a ~950-char Arabic
    # exchange would measure ~4,700 chars against a 3,500 budget and the loop
    # below would drop it to nothing. Pinned by
    # test_store_measures_serialized_size_without_ascii_escaping and
    # test_arabic_history_survives_the_blocking_path.
    while len(trimmed) > 2 and len(json.dumps(trimmed, ensure_ascii=False)) > max_chars:
        trimmed = trimmed[2:]  # drop the oldest user/assistant pair
    return trimmed
