"""Durable chat history: the seam between a turn and the database.

Why this exists alongside ConversationStore
-------------------------------------------
``ConversationStore`` is the *computed prompt window*, not a cache of these
rows. ``append_turn`` there writes back whatever ``_truncate`` returned, and
``_clamp`` rewrites over-long content with ``ELISION_NOTICE`` — so it
deliberately holds different text from what the reader was shown. Treating it as
a write-through cache of the durable rows would let a process restart silently
change the prompt mid-conversation. The two stores answer different questions
and neither is derivable from the other.

Scope
-----
Everything here is Flask-side and privileged. The browser never reaches these
tables directly: readers hold SELECT and DELETE through RLS, and every write
goes through ``chat_append_turn``. See the migration for the argument.

Failure posture
---------------
Persistence is auxiliary to answering. Every method raises
:class:`PersistenceUnavailable` rather than propagating a transport error, and
every caller is expected to report it in-band and keep serving the answer — the
reader has a complete, correctly cited response on screen either way.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from web.utils.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)

# The same bound the People pager clamps to (web/api/admin.py). Shared rather
# than re-picked so two paginated surfaces cannot disagree about what "too much"
# means — and low enough that a hydrated transcript stays under citations.js's
# MAX_TRACKED_ANSWERS cap of 100 answers for any realistic session.
MIN_LOAD_LIMIT = 1
MAX_LOAD_LIMIT = 200
DEFAULT_LOAD_LIMIT = 50


class PersistenceUnavailable(RuntimeError):
    """Durable history could not be reached. Never fatal to answering."""


@dataclass(frozen=True)
class AppendResult:
    """What ``chat_append_turn`` committed.

    ``replayed`` is true when this request id had already been recorded, in
    which case nothing was written and the ids are the originals. It is not an
    error — it is the idempotency working.
    """

    session_id: str
    user_message_id: Optional[str]
    assistant_message_id: Optional[str]
    replayed: bool


@dataclass(frozen=True)
class StoredMessage:
    """One persisted message, with its retrieval set when it has one."""

    message_id: str
    seq: int
    role: str
    content: str
    created_at: Optional[str] = None
    corpus_revision: Optional[str] = None
    model: Optional[str] = None
    lang: Optional[str] = None
    category: Optional[str] = None
    sources: List[Dict[str, Any]] = field(default_factory=list)


# ── uuid canonicalisation ───────────────────────────────────────────────────
# `conv_id` has always been minted as `uuid.uuid4().hex` — 32 characters, no
# dashes. A Postgres `uuid` column accepts that form happily and returns the
# DASHED one, so a value that made a round trip stops comparing equal to the
# value that went in: the ConversationStore key splits into two entries for one
# conversation, and any client-side comparison silently never matches.
#
# So the boundary is enforced here and only here, in Python. Never in SQL — a
# cast that normalises inside the database fixes the column and leaves every
# comparison on this side still wrong.

def canonical_uuid(value: Any) -> Optional[str]:
    """Return the dashed canonical form, or None when this is not a uuid.

    Returns None rather than raising because the inputs are a cookie the reader
    controls and, in production, an identity whose id can legitimately be an
    email: `_authenticate_request` falls back to `user.email` when a provider
    omits `id`. Callers degrade to cache-only history and log; refusing to
    answer because a chat could not be filed would be the wrong trade.
    """
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def new_conversation_id() -> str:
    """Mint a conversation id in the canonical dashed form."""
    return str(uuid.uuid4())


# ── archive keys ────────────────────────────────────────────────────────────

def _salt(name: str) -> Optional[bytes]:
    raw = os.getenv(name) or ""
    return raw.encode("utf-8") if raw else None


# Logged once per process, not once per turn. Unset salts are a SUPPORTED,
# possibly permanent state (.env.example: "Unset is a supported state and
# fails in the safe direction") — a deployment may deliberately run without an
# archive. An ERROR on every single turn forever would be noise, not signal;
# one line at first use is what the roadmap's "fails closed and logs" actually
# calls for. Mirrors SupabaseAdminClient._warned in web/utils/supabase_client.py.
_salt_missing_warned = False


def archive_keys(owner_id: str, session_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Pseudonymous digests for the archive, or ``(None, None)``.

    Computed HERE, from ids the server has already verified, and never read from
    a request body: a caller who supplies its own digest chooses which bucket
    their turns land in, and both the purge path and any frequency analysis
    inherit that choice.

    A missing salt returns ``(None, None)`` so the caller can skip the archive
    row and still record the reader's own history. Writing a null-salted digest
    instead would be worse than not writing at all — it is a stable key derived
    from nothing, indistinguishable later from a real one.
    """
    owner_salt = _salt("ARCHIVE_OWNER_SALT")
    session_salt = _salt("ARCHIVE_SESSION_SALT")
    if not owner_salt or not session_salt:
        global _salt_missing_warned
        if not _salt_missing_warned:
            logger.error(
                "ARCHIVE_OWNER_SALT/ARCHIVE_SESSION_SALT is not set; every "
                "turn's archive row will be skipped for the life of this "
                "process. The reader's own history is unaffected. Set both in "
                "the environment to enable the archive."
            )
            _salt_missing_warned = True
        return None, None

    return (
        hmac.new(owner_salt, str(owner_id).encode("utf-8"), hashlib.sha256).hexdigest(),
        hmac.new(session_salt, str(session_id).encode("utf-8"), hashlib.sha256).hexdigest(),
    )


def clamp_load_limit(value: Any) -> int:
    """Bound a hydration window to what the transcript surface can carry."""
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LOAD_LIMIT
    return max(MIN_LOAD_LIMIT, min(limit, MAX_LOAD_LIMIT))


# ── the backend contract ────────────────────────────────────────────────────

class ChatBackend(Protocol):
    """Durable conversation storage. Implementations must not raise for "empty"."""

    def append_turn(
        self,
        *,
        owner_id: str,
        session_id: str,
        client_request_id: str,
        question: str,
        answer: str,
        sources: List[Dict[str, Any]],
        lang: Optional[str],
        category: Optional[str],
        model: Optional[str],
        corpus_revision: Optional[str],
        owner_key: Optional[str],
        session_key: Optional[str],
        archive_opted_out: bool,
    ) -> AppendResult:
        """Record one exchange, creating the session if it does not exist.

        One transaction: both message rows, every retrieved source, the
        session's ``updated_at``, and the archive row. A repeated
        ``client_request_id`` writes nothing and reports ``replayed``.
        """
        ...

    def load_session(
        self, owner_id: str, session_id: str, *, limit: int = DEFAULT_LOAD_LIMIT,
        before_seq: Optional[int] = None,
    ) -> List[StoredMessage]:
        """The newest ``limit`` messages of one owned session, oldest first.

        An unowned or unknown session id returns ``[]`` — the same answer an
        empty session gives, deliberately, so probing for a stranger's session
        id cannot distinguish "not yours" from "not there".
        """
        ...

    def latest_session(self, owner_id: str) -> Optional[str]:
        """The owner's most recently appended-to session, or None."""
        ...


class SupabaseChatBackend:
    """The real one: the three RPCs, through the service-role client."""

    def __init__(self, client) -> None:
        self._client = client

    def append_turn(
        self, *, owner_id, session_id, client_request_id, question, answer,
        sources, lang, category, model, corpus_revision,
        owner_key, session_key, archive_opted_out,
    ) -> AppendResult:
        try:
            response = self._client.rpc(
                "chat_append_turn",
                {
                    "p_owner_id": owner_id,
                    "p_session_id": session_id,
                    "p_client_request_id": client_request_id,
                    "p_question": question,
                    "p_answer": answer,
                    "p_sources": sources,
                    "p_lang": lang,
                    "p_category": category,
                    "p_model": model,
                    "p_corpus_revision": corpus_revision,
                    "p_owner_key": owner_key,
                    "p_session_key": session_key,
                    # Belt to archive_keys' braces: a missing salt opts the
                    # archive row out here rather than letting the RPC decide.
                    "p_archive_opted_out": bool(archive_opted_out)
                    or owner_key is None
                    or session_key is None,
                },
            ).execute()
        except Exception as exception:
            raise PersistenceUnavailable(str(exception)) from exception

        rows = getattr(response, "data", None) or []
        row = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else {})
        return AppendResult(
            session_id=str(row.get("session_id") or session_id),
            user_message_id=row.get("user_message_id"),
            assistant_message_id=row.get("assistant_message_id"),
            replayed=bool(row.get("replayed")),
        )

    def load_session(
        self, owner_id, session_id, *, limit=DEFAULT_LOAD_LIMIT, before_seq=None
    ) -> List[StoredMessage]:
        try:
            response = self._client.rpc(
                "chat_load_session",
                {
                    "p_owner_id": owner_id,
                    "p_session_id": session_id,
                    "p_limit": clamp_load_limit(limit),
                    "p_before_seq": before_seq,
                },
            ).execute()
        except Exception as exception:
            raise PersistenceUnavailable(str(exception)) from exception

        return [_row_to_message(row) for row in (getattr(response, "data", None) or [])]

    def latest_session(self, owner_id) -> Optional[str]:
        try:
            response = self._client.rpc(
                "chat_latest_session", {"p_owner_id": owner_id}
            ).execute()
        except Exception as exception:
            raise PersistenceUnavailable(str(exception)) from exception

        data = getattr(response, "data", None)
        if isinstance(data, list):
            data = data[0] if data else None
        if isinstance(data, dict):
            data = data.get("chat_latest_session")
        return str(data) if data else None


def _row_to_message(row: Dict[str, Any]) -> StoredMessage:
    return StoredMessage(
        message_id=str(row.get("message_id") or ""),
        seq=int(row.get("seq") or 0),
        role=str(row.get("role") or ""),
        content=str(row.get("content") or ""),
        created_at=row.get("created_at"),
        corpus_revision=row.get("corpus_revision"),
        model=row.get("model"),
        lang=row.get("lang"),
        category=row.get("category"),
        sources=list(row.get("sources") or []),
    )


class InMemoryChatBackend:
    """The test double, and the whole reason the promised tests can run.

    It stores by STRING KEY and performs no uuid cast, which is what lets the
    TESTING bypass identities work: ``test-user-id`` is not a uuid and never
    will be, and rewriting three fixtures into uuids would make every existing
    assertion about them unreadable.

    It reimplements the RPC's guarantees rather than approximating them —
    ownership refusal, seq allocation in pairs, replay as a no-op that does not
    advance the counter — because a double that is laxer than the database turns
    a test suite into a source of false confidence.

    That is not a slogan, and it was not true on the first pass: a review found
    this class happily accepting `source_index = 150`, a 400-character snippet
    and a null document, every one of which Postgres rejects with a CHECK or a
    NOT NULL. Every test in the suite runs against this class, so those three
    constraints were being asserted by nobody. `_validate_sources` below mirrors
    them, and mirrors the *shape* checks too — a JSON payload that is not an
    array aborts `jsonb_array_elements` in the RPC and rolls back the whole
    turn, so the double must not sail past it.
    """

    # Mirrors chat_message_sources' constraints exactly. When the migration
    # changes, this changes with it — a divergence here is a test suite quietly
    # proving something the database will not honour.
    _MAX_SOURCE_INDEX = 99
    _MAX_SNIPPET_CHARS = 321

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._messages: Dict[str, List[StoredMessage]] = {}
        # (session_id, client_request_id) -> AppendResult, for replay.
        self._turns: Dict[Tuple[str, str], AppendResult] = {}
        # Mirrors public.chat_archive so a test can assert one row per turn.
        self.archive: List[Dict[str, Any]] = []

    def _validate_sources(self, sources: Any) -> List[Dict[str, Any]]:
        """Reject exactly what `chat_message_sources` would reject.

        Raises :class:`PersistenceUnavailable` because that is what a constraint
        violation looks like to a caller: the RPC aborts, the transaction rolls
        back, and `_persist_turn` reports the turn unfiled while the reader
        keeps their answer. A test that trips one of these should see the same
        outcome production would.
        """
        # Not a list is the `jsonb_typeof <> 'array'` case, which the RPC
        # coerces to empty rather than aborting.
        if not isinstance(sources, list):
            return []

        seen: set = set()
        validated: List[Dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, dict):
                raise PersistenceUnavailable(f"source is not an object: {source!r}")

            index = source.get("source_index")
            if not isinstance(index, int) or isinstance(index, bool):
                raise PersistenceUnavailable(f"source_index is not an integer: {index!r}")
            if not 1 <= index <= self._MAX_SOURCE_INDEX:
                raise PersistenceUnavailable(f"source_index {index} outside 1..{self._MAX_SOURCE_INDEX}")
            if index in seen:
                raise PersistenceUnavailable(f"duplicate source_index {index}")
            seen.add(index)

            snippet = source.get("snippet") or ""
            if len(snippet) > self._MAX_SNIPPET_CHARS:
                raise PersistenceUnavailable(
                    f"snippet is {len(snippet)} chars, over {self._MAX_SNIPPET_CHARS}"
                )

            # `document` and `category` are NOT NULL in the schema, but the RPC
            # coalesces a missing key to ''. Mirror the coalesce, not the
            # constraint — the constraint is unreachable through that path.
            validated.append({
                **source,
                "document": source.get("document") or "",
                "category": source.get("category") or "",
                "snippet": snippet,
                "cited": bool(source.get("cited")),
            })
        return validated

    def append_turn(
        self, *, owner_id, session_id, client_request_id, question, answer,
        sources, lang, category, model, corpus_revision,
        owner_key, session_key, archive_opted_out,
    ) -> AppendResult:
        owner_id, session_id = str(owner_id), str(session_id)
        with self._lock:
            # ORDER MATTERS, and it mirrors the RPC exactly: ownership, then
            # replay, then validation, then mutation.
            #
            # Validating first — the obvious reading, and what this did at
            # first — makes the double stricter than Postgres on the one path
            # where it must not be. The RPC's replay branch RETURNS before it
            # ever parses p_sources, so a retry carrying a malformed payload is
            # a successful no-op there. Validating up front turned that same
            # retry into a raised error here, and no test would have caught the
            # difference because the double is what the tests run against.
            existing = self._sessions.get(session_id)
            if existing is not None and existing["owner_id"] != owner_id:
                raise PersistenceUnavailable(
                    f"chat session {session_id} is not owned by {owner_id}"
                )

            replay = self._turns.get((session_id, str(client_request_id)))
            if replay is not None:
                # replayed=True, which the cached result cannot carry: it is the
                # original call's answer, and that call was not a replay. Without
                # this the flag is False forever and _persist_turn's replay branch
                # is dead code under test.
                return AppendResult(
                    replay.session_id, replay.user_message_id,
                    replay.assistant_message_id, True,
                )

            # Only a genuinely new turn is validated, and it is validated before
            # anything is written, so a rejected payload leaves no half-written
            # session behind — the transaction gives the RPC that for free.
            sources = self._validate_sources(sources)

            session = existing
            if session is None:
                session = {"owner_id": owner_id, "next_seq": 1, "order": len(self._sessions)}
                self._sessions[session_id] = session
                self._messages[session_id] = []

            seq = session["next_seq"]
            session["next_seq"] = seq + 2
            # Ordering handle for latest_session. Monotonic and explicit rather
            # than a wall clock: two turns in the same test land in the same
            # millisecond and the tiebreaker would be undefined.
            session["order"] = max(
                (s["order"] for s in self._sessions.values()), default=0
            ) + 1

            user_id = str(uuid.uuid4())
            assistant_id = str(uuid.uuid4())
            # Mirrors the column's `default now()`. The double omitted this and
            # every test still passed, because nothing downstream looked — until
            # the transcript did, and a hydrated turn would have carried no time
            # at all while the real RPC returns one. That is the same drift this
            # class was already corrected for once: a double laxer than the
            # schema lets a test claim a guarantee Postgres makes and the double
            # does not.
            occurred_at = datetime.now(timezone.utc).isoformat()
            self._messages[session_id].extend(
                [
                    StoredMessage(user_id, seq, "user", question, created_at=occurred_at),
                    StoredMessage(
                        assistant_id, seq + 1, "assistant", answer,
                        created_at=occurred_at,
                        corpus_revision=corpus_revision, model=model,
                        lang=lang, category=category, sources=list(sources or []),
                    ),
                ]
            )

            if not archive_opted_out and owner_key and session_key:
                # (owner_key, session_key, turn_key), matching the SQL unique
                # constraint. Omitting session_key made the double drop a second
                # turn that Postgres would archive — one request id reused across
                # two conversations — so a test could "prove" one archive row
                # where production writes two.
                if not any(
                    row["owner_key"] == owner_key
                    and row["session_key"] == session_key
                    and row["turn_key"] == str(client_request_id)
                    for row in self.archive
                ):
                    self.archive.append(
                        {
                            "owner_key": owner_key,
                            "session_key": session_key,
                            "turn_key": str(client_request_id),
                            "question": question,
                            "answer": answer,
                            "sources": list(sources or []),
                            "lang": lang,
                            "category": category,
                            "model": model,
                            "corpus_revision": corpus_revision,
                        }
                    )

            result = AppendResult(session_id, user_id, assistant_id, False)
            self._turns[(session_id, str(client_request_id))] = result
            return result

    def load_session(
        self, owner_id, session_id, *, limit=DEFAULT_LOAD_LIMIT, before_seq=None
    ) -> List[StoredMessage]:
        with self._lock:
            session = self._sessions.get(str(session_id))
            if session is None or session["owner_id"] != str(owner_id):
                return []
            rows = [
                m for m in self._messages[str(session_id)]
                if before_seq is None or m.seq < before_seq
            ]
            return rows[-clamp_load_limit(limit):]

    def latest_session(self, owner_id) -> Optional[str]:
        with self._lock:
            owned = [
                (session["order"], session_id)
                for session_id, session in self._sessions.items()
                if session["owner_id"] == str(owner_id)
            ]
            return max(owned)[1] if owned else None

    # Test affordance, not part of the Protocol.
    def sessions_for(self, owner_id: str) -> List[str]:
        with self._lock:
            return [
                session_id for session_id, session in self._sessions.items()
                if session["owner_id"] == str(owner_id)
            ]


def get_chat_backend() -> Optional[ChatBackend]:
    """The real backend, or None when this deployment has no database.

    None means "no durable history available" and is not an error: the same
    posture `get_admin_backend` takes. Chat still answers from the in-RAM
    window, which is exactly what it did before this feature existed.
    """
    client = get_supabase_admin()
    if client is None:
        return None
    return SupabaseChatBackend(client)
