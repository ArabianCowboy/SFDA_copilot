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

# The sidebar's page. Smaller than the hydration window on purpose: that one is
# bounded by what a transcript surface can carry, this one by what a reader will
# scan before reaching for "load more". 30 fills the column roughly twice over
# at every breakpoint the sidebar has.
MIN_LIST_LIMIT = 1
MAX_LIST_LIMIT = 100
DEFAULT_LIST_LIMIT = 30

# Mirrors `chat_sessions.title`'s `char_length(title) between 1 and 120`.
# Clamped in Flask BEFORE the RPC, never left to the CHECK: a constraint
# violation inside a `security definer` function surfaces a client mistake as a
# 500, and the roadmap's §3 says so explicitly.
MAX_TITLE_CHARS = 120


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
class SessionSummary:
    """One row of the sidebar. Deliberately not one row of a transcript.

    No preview snippet, and that is a decision rather than an omission: a
    snippet means joining ``chat_messages`` for every listed conversation on the
    request that draws the sidebar, and the title is already the opening
    question. ``message_count`` costs nothing by comparison — it is
    ``next_seq - 1``, read from a column the session row already carries.

    ``title`` stays optional. Sessions written before first-turn titling shipped
    have none, and the client renders a localised fallback rather than this
    layer inventing one from data it does not have.
    """

    session_id: str
    title: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    message_count: int


@dataclass(frozen=True)
class SessionPage:
    """A page of sessions plus the cursor that continues it.

    The cursor is ``(updated_at, id)`` of the last row, and it is None when the
    page was not full. "Not full" is the only honest end-of-list signal a keyset
    pager has — asking for one extra row to detect it would be a second read on
    every page to save one read at the end.
    """

    sessions: List[SessionSummary]
    next_cursor: Optional[Tuple[str, str]]


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


def clamp_list_limit(value: Any) -> int:
    """Bound a sidebar page."""
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LIST_LIMIT
    return max(MIN_LIST_LIMIT, min(limit, MAX_LIST_LIMIT))


def clamp_title(value: Any) -> Optional[str]:
    """A title the ``chat_sessions.title`` CHECK will accept, or None.

    Three things happen here and each closes a specific hole.

    * **Whitespace is collapsed, not merely stripped.** A question pasted out of
      a PDF arrives full of newlines and runs of spaces; left alone they survive
      into the sidebar as a title with a hole in the middle, and they count
      toward the 120-character bound while carrying no information.
    * **The cut lands on a word boundary** when there is one to land on, with a
      real ellipsis rather than three periods. A regulatory question truncated
      mid-word — "Bioequivalence requirements for immediate-rele" — reads as
      damage rather than as abbreviation.
    * **Empty becomes None, never ''.** The column's CHECK rejects a
      zero-length title, and the sidebar already renders an "untitled" fallback
      for null. Returning '' would turn a blank question into a 500.

    Deliberately NOT done: stripping question boilerplate ("What are the
    requirements for…", "ما هي اشتراطات…"). A heuristic phrase list is one
    language's grammar wearing a general rule's clothing, it would have to be
    maintained in two scripts, and its failure mode is silently mangling the one
    string the reader uses to recognise their own conversation. The opening
    question, trimmed, is what they typed.
    """
    if value is None:
        return None
    collapsed = " ".join(str(value).split())
    if not collapsed:
        return None
    if len(collapsed) <= MAX_TITLE_CHARS:
        return collapsed

    # One character of the budget belongs to the ellipsis.
    head = collapsed[: MAX_TITLE_CHARS - 1]
    # Only rewind to a space when one exists late enough that the result is
    # still recognisably the question. A 119-character run with no space at all
    # — plausible in an identifier, a URL, or a language this app does not
    # segment — is cut where it falls rather than collapsed to nothing.
    boundary = head.rfind(" ")
    if boundary >= MAX_TITLE_CHARS // 2:
        head = head[:boundary]
    return f"{head.rstrip()}…"


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
        title: Optional[str] = None,
    ) -> AppendResult:
        """Record one exchange, creating the session if it does not exist.

        One transaction: both message rows, every retrieved source, the
        session's ``updated_at``, the title when it has none, and the archive
        row. A repeated ``client_request_id`` writes nothing and reports
        ``replayed``.

        ``title`` is a CANDIDATE, applied only when the session has no title
        yet. Callers pass the current question on every turn and let the
        database decide; asking "is this the first turn?" first would be a round
        trip that the answer immediately races.
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

    def list_sessions(
        self,
        owner_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: Optional[Tuple[str, str]] = None,
    ) -> SessionPage:
        """One page of the owner's conversations, newest activity first."""
        ...

    def rename_session(self, owner_id: str, session_id: str, title: Optional[str]) -> bool:
        """Set one owned session's title. False when it is not theirs.

        Does not touch ``updated_at``: that column means "last spoken in", and a
        rename must not lift a months-old conversation to the top of Today.
        """
        ...

    def delete_session(self, owner_id: str, session_id: str) -> bool:
        """Delete one owned session and its messages. False when not theirs."""
        ...


class SupabaseChatBackend:
    """The real one: the three RPCs, through the service-role client."""

    def __init__(self, client) -> None:
        self._client = client

    def append_turn(
        self, *, owner_id, session_id, client_request_id, question, answer,
        sources, lang, category, model, corpus_revision,
        owner_key, session_key, archive_opted_out, title=None,
    ) -> AppendResult:
        try:
            response = self._client.rpc(
                "chat_append_turn",
                {
                    "p_title": clamp_title(title),
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

    def list_sessions(
        self, owner_id, *, limit=DEFAULT_LIST_LIMIT, cursor=None
    ) -> SessionPage:
        limit = clamp_list_limit(limit)
        cursor_updated_at, cursor_id = cursor if cursor else (None, None)
        try:
            response = self._client.rpc(
                "chat_list_sessions",
                {
                    "p_owner_id": owner_id,
                    "p_limit": limit,
                    "p_cursor_updated_at": cursor_updated_at,
                    "p_cursor_id": cursor_id,
                },
            ).execute()
        except Exception as exception:
            raise PersistenceUnavailable(str(exception)) from exception

        rows = getattr(response, "data", None) or []
        sessions = [_row_to_summary(row) for row in rows]
        return SessionPage(sessions=sessions, next_cursor=_cursor_after(sessions, limit))

    def rename_session(self, owner_id, session_id, title) -> bool:
        try:
            response = self._client.rpc(
                "chat_rename_session",
                {
                    "p_owner_id": owner_id,
                    "p_session_id": session_id,
                    # Clamped here, not in SQL. The column's CHECK would turn an
                    # over-long title into a 500 raised inside a `security
                    # definer` function; this makes it a shorter title.
                    "p_title": clamp_title(title),
                },
            ).execute()
        except Exception as exception:
            raise PersistenceUnavailable(str(exception)) from exception
        return bool(_scalar(response, "chat_rename_session"))

    def delete_session(self, owner_id, session_id) -> bool:
        try:
            response = self._client.rpc(
                "chat_delete_session",
                {"p_owner_id": owner_id, "p_session_id": session_id},
            ).execute()
        except Exception as exception:
            raise PersistenceUnavailable(str(exception)) from exception
        return bool(_scalar(response, "chat_delete_session"))


def _scalar(response: Any, key: str) -> Any:
    """Unwrap a scalar-returning RPC, whichever shape PostgREST chose.

    A `returns boolean` function comes back as a bare value, and the same call
    through a different client version comes back as ``[{"name": value}]``.
    ``latest_session`` already hedges both ways; this is that hedge, named, so
    the next scalar RPC does not reinvent it a third time.
    """
    data = getattr(response, "data", None)
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict):
        data = data.get(key, next(iter(data.values()), None))
    return data


def _cursor_after(
    sessions: List[SessionSummary], limit: int
) -> Optional[Tuple[str, str]]:
    """The keyset cursor that continues this page, or None at the end.

    A short page is the end of the list. A FULL page is not proof there is more
    — the next request may return nothing — but offering the cursor costs one
    empty read in that case, while withholding it would need a lookahead row on
    every page to save it.
    """
    if len(sessions) < limit or not sessions:
        return None
    last = sessions[-1]
    if not last.updated_at or not last.session_id:
        # A row with no ordering key cannot be paged past. Ending the list is
        # the honest answer; a cursor built from a null would silently return
        # the first page again, forever.
        return None
    return (last.updated_at, last.session_id)


def _row_to_summary(row: Dict[str, Any]) -> SessionSummary:
    title = row.get("title")
    return SessionSummary(
        session_id=str(row.get("id") or ""),
        # Preserved as None rather than coerced to ''. "This conversation has no
        # title" and "its title is empty" are the same fact to the database and
        # different facts to the client, which renders a localised fallback for
        # the first and would render a blank row for the second.
        title=str(title) if title else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        message_count=int(row.get("message_count") or 0),
    )


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
        owner_key, session_key, archive_opted_out, title=None,
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
                session = {
                    "owner_id": owner_id,
                    "next_seq": 1,
                    "order": len(self._sessions),
                    "title": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                self._sessions[session_id] = session
                self._messages[session_id] = []

            # Mirrors `title = coalesce(title, …)` in the RPC's seq-claiming
            # UPDATE: set when null, never overwritten, and applied only on the
            # new-turn path — the replay branch above has already returned. A
            # double that overwrote here would let a test prove that renaming a
            # conversation survives the next turn when in fact it would not.
            if session.get("title") is None:
                session["title"] = clamp_title(title)

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
            # Mirrors `updated_at = now()` on the seq-claiming UPDATE, and it is
            # a WALL CLOCK on purpose even though `order` above deliberately is
            # not. The two answer different questions: `order` only has to rank
            # this process's own sessions for latest_session, while updated_at
            # is read by the client, grouped into Today / Yesterday / Older, and
            # used as half the keyset cursor. A monotonic counter cannot be
            # grouped by date, and a double that fabricated one would let a test
            # pass over a sidebar that renders every conversation under the
            # wrong heading.
            session["updated_at"] = occurred_at
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

    def list_sessions(
        self, owner_id, *, limit=DEFAULT_LIST_LIMIT, cursor=None
    ) -> SessionPage:
        limit = clamp_list_limit(limit)
        with self._lock:
            rows = [
                SessionSummary(
                    session_id=session_id,
                    title=session.get("title"),
                    created_at=session.get("created_at"),
                    updated_at=session.get("updated_at"),
                    # `next_seq - 1`, exactly as the RPC derives it, rather than
                    # `len(self._messages[...])`. They agree today; deriving it
                    # the same way is what keeps them agreeing if either side
                    # ever changes how a turn is counted.
                    message_count=int(session.get("next_seq", 1)) - 1,
                )
                for session_id, session in self._sessions.items()
                if session["owner_id"] == str(owner_id)
            ]

            # `order by updated_at desc, id desc`, and the tiebreaker is not
            # optional here either: two sessions written inside one microsecond
            # share a timestamp, and without the id the cursor could skip a row
            # or return one twice forever.
            rows.sort(key=lambda s: (s.updated_at or "", s.session_id), reverse=True)

            if cursor and cursor[0] and cursor[1]:
                rows = [
                    s for s in rows
                    if (s.updated_at or "", s.session_id) < (cursor[0], cursor[1])
                ]

            page = rows[:limit]
            return SessionPage(sessions=page, next_cursor=_cursor_after(page, limit))

    def rename_session(self, owner_id, session_id, title) -> bool:
        with self._lock:
            session = self._sessions.get(str(session_id))
            # "Not yours" and "not there" are the same answer, matching the RPC.
            if session is None or session["owner_id"] != str(owner_id):
                return False
            session["title"] = clamp_title(title)
            # updated_at is NOT touched. The RPC goes out of its way not to; a
            # double that bumped it would let a test prove the sidebar holds its
            # order across a rename when in production it would shuffle.
            return True

    def delete_session(self, owner_id, session_id) -> bool:
        with self._lock:
            key = str(session_id)
            session = self._sessions.get(key)
            if session is None or session["owner_id"] != str(owner_id):
                return False
            del self._sessions[key]
            # The cascade, by hand. `chat_messages` goes through the composite
            # FK's ON DELETE CASCADE and `chat_message_sources` follows from
            # there, so a double that left messages behind would be laxer than
            # the schema in the one direction that matters for a delete.
            self._messages.pop(key, None)
            # And the idempotency keys with them. Left in place, re-asking the
            # same question with the same client_request_id after a delete would
            # report `replayed` and write nothing — a turn that vanishes.
            for turn_key in [k for k in self._turns if k[0] == key]:
                del self._turns[turn_key]
            return True

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
