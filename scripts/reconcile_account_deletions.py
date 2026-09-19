"""The deletion-saga reconcile driver: a systemd one-shot, not a thread.

Runs the deletion saga's post-grace steps for every due row in
``public.account_deletions`` (slice 2a, ``supabase/pending/07`` +
``supabase/pending/10``): claim (lease-based, so two drivers cannot run one
step twice) → purge transcripts → re-purge and begin the auth delete →
delete the GoTrue user → record the outcome → complete.

WHY A ONE-SHOT AND NOT A THREAD, A CRON LINE, `pg_cron`, OR AN IN-FLASK
SCHEDULER. ``deploy/sfda-copilot.service`` runs ``--max-requests 1000``, so
the worker recycles roughly every thousand requests — under any thread's
feet. A daemon thread dying mid-GoTrue-call produces exactly the
unknown-outcome state with nobody left to reconcile it. And an admin-gated
HTTP endpoint would need a stored admin password: a leak of it grants the
whole console including ``change_email``, and the timer's account would count
as an enabled administrator. This entry point uses the service key ALREADY
in ``.env``, speaks to the database directly, adds NO credential, and stores
NO admin password.

RECONCILIATION RULE (plan §5). On an ambiguous outcome — the transport
failed and GoTrue may already have committed — call ``user_exists()``: if
GoTrue admin get-by-id no longer returns the user, the step SUCCEEDED
whatever the transport said (recorded as ``not_found``, which the saga
treats as success, never failure).

NEVER logs, stores, or transmits the deleted reader's email, IP, or user
agent: log lines carry the saga's DL-codes and the ledger's uuid key only
(decision D3 — uuids and timestamps are what the ledger itself holds).

NEVER calls ``revoke_sessions`` and NEVER sets a GoTrue ban: both would lock
the reader out of the grace-window cancel path and make the grace fake.

Exit status is non-zero when any due row ends failed, ambiguous, or
unexpected, so the ``.timer`` unit surfaces it.

Usage::

    python scripts/reconcile_account_deletions.py
    python -m scripts.reconcile_account_deletions
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("reconcile_account_deletions")

# Runnable EITHER as a module (`python -m scripts.reconcile_account_deletions`
# from the repo root) OR as a file (`python
# scripts/reconcile_account_deletions.py`). The file form puts `scripts/` —
# not the root — on `sys.path`, so the `web.*` imports below would fail;
# anchor the root explicitly. Harmless in the module form (already present)
# and under pytest (the guard keeps it from duplicating).
_ROOT = Path(__file__).resolve().parents[1]
if (_ROOT / "web").is_dir() and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# The lease window handed to the claim RPC, in seconds. Matches the saga's
# own default (``p_lease_seconds integer default 300``): long enough for a
# purge plus one GoTrue round trip, short enough that a crashed driver does
# not hold a row past the next timer tick by much.
LEASE_SECONDS = 300

# States the driver picks up. ``completed``/``cancelled`` are terminal and
# never due; ``auth_delete_begun`` has no claim edge OUT of it (the outcome
# step is serialized by state, not by lease), so a row found there is driven
# straight at the GoTrue step rather than claimed first — that is what closes
# the crash window between ``begin_auth_delete`` committing and the provider
# call returning.
_CLAIMABLE = ("pending", "failed", "purging")


def _rpc_code(exception: BaseException) -> str:
    """A DL-code for the ledger, never a message (D3: messages can carry PII)."""
    code = getattr(exception, "code", None)
    if isinstance(code, str) and code:
        return code
    return "driver_failed"


def _rpc(db: Any, name: str, params: dict) -> Any:
    """One saga RPC; returns the decoded row (or None for an empty claim)."""
    response = db.rpc(name, params).execute()
    return getattr(response, "data", response)


def _fail(db: Any, user_id: str, code: str) -> None:
    _rpc(db, "account_deletion_fail", {"p_owner_id": user_id, "p_error_code": code})


class _AlreadySettled(Exception):
    """The saga left the state this step requires before the outcome was
    recorded — the console and the timer drove the same row concurrently and
    the other driver won."""


def _record_settled(db: Any, user_id: str, outcome: str, code: str | None = None) -> Any:
    """``_record``, except a DL004 refusal becomes ``_AlreadySettled``.

    The ``auth_delete_begun`` branch takes no lease (no claim edge leaves
    that state — the outcome step is serialized by state, not by lease), so
    two drivers CAN overlap there. When the loser records its outcome the
    row is already terminal and the RPC raises DL004. That is not a failure
    of this drive — the deletion the drive was performing has already been
    recorded by the winner — so it must surface as settled, never as an
    error that reports a successful deletion "unexpected".
    """
    try:
        return _record(db, user_id, outcome, code)
    except Exception as exc:
        if _rpc_code(exc) == "DL004":
            raise _AlreadySettled from exc
        raise


def _fail_settled(db: Any, user_id: str, code: str) -> None:
    """``_fail`` with the same overlap rule: no live saga left to fail means
    the other driver already moved the row somewhere terminal."""
    try:
        _fail(db, user_id, code)
    except Exception as exc:
        if _rpc_code(exc) == "DL004":
            raise _AlreadySettled from exc
        raise


def _complete_settled(db: Any, user_id: str) -> Any:
    """``account_deletion_complete`` with the same overlap rule."""
    try:
        return _rpc(db, "account_deletion_complete", {"p_owner_id": user_id})
    except Exception as exc:
        if _rpc_code(exc) == "DL004":
            raise _AlreadySettled from exc
        raise


def _record(db: Any, user_id: str, outcome: str, code: str | None = None) -> Any:
    params: dict[str, Any] = {"p_owner_id": user_id, "p_outcome": outcome}
    if code is not None:
        params["p_error_code"] = code
    return _rpc(db, "account_deletion_record_auth_outcome", params)


def _drive_auth_delete(db: Any, dispatcher: Any, user_id: str) -> str:
    """The GoTrue step plus its recording. Returns completed/failed/ambiguous.

    Returns ``settled`` when the outcome recording raises DL004: the other
    driver already moved the row terminal while this drive was in flight.
    ``main`` treats that as nothing-failed, and the console reports it
    honestly rather than as an error.
    """
    try:
        return _drive_auth_delete_inner(db, dispatcher, user_id)
    except _AlreadySettled:
        logger.warning("delete already settled for %s", user_id)
        return "settled"


def _drive_auth_delete_inner(db: Any, dispatcher: Any, user_id: str) -> str:
    """The GoTrue step plus its recording. Returns completed/failed/ambiguous."""
    # Imported here so importing this module never requires the app's
    # dependencies beyond what the driver itself needs.
    from web.services.auth_admin import AuthAdminRefused

    try:
        dispatcher.delete_user(user_id)
    except AuthAdminRefused as refusal:
        if not refusal.ambiguous:
            _record_settled(db, user_id, "failed", refusal.code)
            logger.warning("delete refused for %s (%s)", user_id, refusal.code)
            return "failed"
        # Ambiguous: the transport failed and GoTrue may already have
        # committed. Reconcile through get-by-id before recording anything.
        try:
            gone = not dispatcher.user_exists(user_id)
        except AuthAdminRefused as check_refusal:
            _record_settled(db, user_id, "ambiguous", check_refusal.code)
            logger.warning("delete outcome unknown for %s (%s)", user_id, check_refusal.code)
            return "ambiguous"
        if gone:
            _record_settled(db, user_id, "not_found")
            logger.info("delete reconciled as gone for %s", user_id)
        else:
            _record_settled(db, user_id, "ambiguous", refusal.code)
            logger.warning("delete outcome unknown for %s (%s)", user_id, refusal.code)
            return "ambiguous"
    except Exception:
        logger.exception("delete raised unexpectedly for %s", user_id)
        _record_settled(db, user_id, "ambiguous", "driver_unexpected")
        return "ambiguous"
    else:
        _record_settled(db, user_id, "deleted")
    try:
        _complete_settled(db, user_id)
    except _AlreadySettled:
        # The row went terminal under us (the overlap this module exists to
        # survive): propagate as settled, never as a failure. The clause is
        # required, not decorative — _AlreadySettled subclasses Exception.
        raise
    except Exception as exc:
        # DL006: the profile row survived, so PII remains and completion must
        # not be recorded — fail closed and let an operator look.
        code = _rpc_code(exc)
        try:
            _fail_settled(db, user_id, code)
        except _AlreadySettled:
            raise
        except Exception:
            logger.exception("could not record failure for %s", user_id)
        logger.warning("completion refused for %s (%s)", user_id, code)
        return "failed"
    logger.info("deletion completed for %s", user_id)
    return "completed"


def reconcile_one(db: Any, dispatcher: Any, user_id: str, from_state: str) -> str:
    """Drive one saga row one pass. Returns a short outcome word for ``main``.

    ``unclaimed`` is NORMAL (another driver holds the lease, or the row is
    not due) — not an error, not a failure, exit 0. ``settled`` is NORMAL
    too: the other driver moved the row terminal while this drive was
    recording its outcome (DL004 on an outcome record), so there is nothing
    left to drive and nothing failed.
    """
    # A row already at `auth_delete_begun` has passed both purge steps; the
    # only thing left to resolve is the provider call whose outcome was never
    # recorded (a crashed driver, or an `ambiguous` result the SQL side cannot
    # settle — only `user_exists()` can). Drive it straight at the GoTrue step.
    #
    # This branch is the whole point of `auth_delete_begun` being unclaimable,
    # and it must come BEFORE the purge loop below: both RPCs there require
    # `state = 'purging'` with a live lease (`10_account_deletion_saga_rpcs.sql`
    # :242, :290), so falling through would raise DL004, record a failure the
    # saga never suffered, and inflate `attempt_count` on every tick — turning
    # the crash window this design exists to close into a guaranteed failure.
    if from_state == "auth_delete_begun":
        return _drive_auth_delete(db, dispatcher, user_id)

    if from_state in _CLAIMABLE:
        try:
            claimed = _rpc(
                db,
                "account_deletion_claim",
                {
                    "p_owner_id": user_id,
                    "p_from_state": from_state,
                    "p_lease_seconds": LEASE_SECONDS,
                },
            )
        except Exception as exc:
            logger.warning("claim refused for %s (%s)", user_id, _rpc_code(exc))
            return "unclaimed"
        if not claimed:
            return "unclaimed"

    for step in ("account_deletion_purge_transcripts", "account_deletion_begin_auth_delete"):
        try:
            _rpc(db, step, {"p_owner_id": user_id})
        except Exception as exc:
            code = _rpc_code(exc)
            try:
                _fail(db, user_id, code)
            except Exception:
                logger.exception("could not record failure for %s", user_id)
            logger.warning("%s refused for %s (%s)", step, user_id, code)
            return "failed"

    return _drive_auth_delete(db, dispatcher, user_id)


def _due_rows(db: Any) -> list[dict]:
    """Every non-terminal row whose next attempt is due. Uuids only (D3)."""
    # Two ``neq`` filters rather than a not-in: the pinned postgrest build
    # exposes ``in_`` but no negated form, and ``neq`` twice is the same AND.
    # The timestamp is computed here, not as SQL ``now()`` — PostgREST would
    # compare against the literal string otherwise.
    now = datetime.now(timezone.utc).isoformat()
    response = (
        db.table("account_deletions")
        .select("user_id,state")
        .neq("state", "completed")
        .neq("state", "cancelled")
        .lte("next_attempt_at", now)
        .execute()
    )
    rows = getattr(response, "data", response) or []
    return [row for row in rows if isinstance(row, dict) and row.get("user_id")]


def _build_db() -> Any:
    """A service-role client from the environment (``.env`` fills the gaps).

    ``override=False`` so a real environment — the systemd unit's
    ``EnvironmentFile`` included — always wins over the file (see
    ``web/tests/test_dotenv_precedence.py`` for the rule this obeys).
    """
    from dotenv import load_dotenv

    from supabase import create_client

    root = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=root / ".env", override=False)

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) "
            "are required; the timer already provides them via EnvironmentFile."
        )
    return create_client(url, key)


def _build_dispatcher(db: Any) -> Any:
    from web.services.auth_admin import SupabaseAuthAdminDispatcher

    return SupabaseAuthAdminDispatcher(db)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit status (0 = nothing failed)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    _ = argv  # no flags today; unknown ones are ignored, not an error

    try:
        db = _build_db()
        dispatcher = _build_dispatcher(db)
    except SystemExit:
        raise
    except Exception:
        logger.exception("driver could not start")
        return 2

    try:
        rows = _due_rows(db)
    except Exception:
        logger.exception("driver could not read due rows")
        return 2

    if not rows:
        logger.info("nothing due")
        return 0

    failures = 0
    for row in rows:
        try:
            outcome = reconcile_one(db, dispatcher, str(row["user_id"]), str(row.get("state")))
        except Exception:
            logger.exception("driver raised unexpectedly for %s", row.get("user_id"))
            outcome = "unexpected"
        if outcome in ("failed", "ambiguous", "unexpected"):
            failures += 1
    if failures:
        logger.warning("%d of %d due row(s) need attention", failures, len(rows))
        return 1
    logger.info("drove %d due row(s), nothing failed", len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
