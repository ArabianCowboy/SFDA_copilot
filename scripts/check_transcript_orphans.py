"""The transcript-orphan detector: a read-only systemd one-shot, not a cleanup.

``public.chat_sessions.owner_id`` has no foreign key (the ``ON DELETE
RESTRICT`` migration was deleted on 2026-09-19 rather than kept parked — see
the "`chat_sessions.owner_id` still has no foreign key" entry in ``TODO.md``
for the full reasoning, including the two sequences that can leave a
transcript behind after an account deletion completes). Orphaned transcripts
would be invisible: unreachable through RLS (no ``auth.uid()`` will ever match
a deleted user) and unreachable through every RPC (all filter
``p_owner_id``). Nothing queries for them. This script is the thing that does.

It runs the orphan query through the service-role client::

    select s.id, s.owner_id, s.created_at
      from public.chat_sessions s
      left join public.profiles p on p.id = s.owner_id
     where p.id is null

(PostgREST exposes no join, so the script pages both tables and diffs them in
memory: session ``id``/``owner_id``/``created_at`` against profile ``id``.)

READ-ONLY BY CONSTRUCTION. This script reports; it never deletes anything.
There is no code path in it that issues a DELETE — no RPC, no
``table().delete()``, no SQL with the word in it.

NEVER logs, stores, or transmits message text or an email: log lines carry
session/owner UUIDs, counts and timestamps only (the deletion ledger's rule —
UUIDs, counts and timestamps are what may leave the database).

A hit is NOT automatically a deleted-account leftover and must never be
auto-deleted. This app deliberately tolerates an ``auth.users`` row with no
``profiles`` row — see
``supabase/migrations/20260828143044_touch_last_seen_tolerates_a_profileless_account.sql``.
Investigate before touching anything. Any hit is an incident, not cleanup.

Exit status is 0 when there are no orphans, 1 when there are, 2 when the
check itself could not run — so the ``.timer`` unit surfaces a hit and a
broken check differently.

Usage::

    python scripts/check_transcript_orphans.py [--quiet]
    python -m scripts.check_transcript_orphans [--quiet]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("check_transcript_orphans")

# Runnable EITHER as a module (`python -m scripts.check_transcript_orphans`
# from the repo root) OR as a file (`python
# scripts/check_transcript_orphans.py`). The file form puts `scripts/` —
# not the root — on `sys.path`, so the `web.*` imports below would fail;
# anchor the root explicitly. Harmless in the module form (already present)
# and under pytest (the guard keeps it from duplicating).
_ROOT = Path(__file__).resolve().parents[1]
if (_ROOT / "web").is_dir() and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# The caveat a half-awake operator will get wrong at 3am. Carried in
# `--help`, this docstring, AND the non-zero log output — all three, because
# each is the one that gets read in a different incident.
_CAVEAT = (
    "A hit is NOT automatically a deleted-account leftover and must never be "
    "auto-deleted. This app deliberately tolerates an `auth.users` row with no "
    "`profiles` row — see "
    "`supabase/migrations/20260828143044_touch_last_seen_tolerates_a_profileless_account.sql`. "
    "Investigate before touching anything. Any hit is an incident, not cleanup."
)

# One PostgREST page per round trip. The corpus is small; the loop below keeps
# paging anyway so a silent 1000-row default can never turn into a false
# "clean".
_PAGE_SIZE = 1000


def _fetch_all(db: Any, table: str, columns: str) -> list[dict]:
    """Every row of ``table`` (``columns`` only), one page at a time."""
    rows: list[dict] = []
    offset = 0
    while True:
        response = db.table(table).select(columns).range(offset, offset + _PAGE_SIZE - 1).execute()
        batch = getattr(response, "data", response) or []
        rows.extend(row for row in batch if isinstance(row, dict))
        if len(batch) < _PAGE_SIZE:
            return rows
        offset += _PAGE_SIZE


def _find_orphans(db: Any) -> list[dict]:
    """Sessions whose owner has no ``profiles`` row. UUIDs/timestamps only."""
    sessions = _fetch_all(db, "chat_sessions", "id,owner_id,created_at")
    profiles = _fetch_all(db, "profiles", "id")
    known = {row.get("id") for row in profiles}
    return [row for row in sessions if row.get("owner_id") not in known]


def _build_db() -> Any:
    """A service-role client from the environment (``.env`` fills the gaps).

    ``override=False`` so a real environment — the systemd unit's
    ``EnvironmentFile`` included — always wins over the file (see
    ``web/tests/test_dotenv_precedence.py`` for the rule this obeys).

    Goes through ``get_supabase_admin``: the key bypasses every RLS policy,
    which is exactly what makes otherwise-invisible rows visible.
    """
    from dotenv import load_dotenv

    root = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=root / ".env", override=False)

    # Imported here so importing this module never requires the app's
    # dependencies beyond what the checker itself needs.
    from web.utils.supabase_client import get_supabase_admin

    db = get_supabase_admin()
    if db is None:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) "
            "are required; the timer already provides them via EnvironmentFile."
        )
    return db


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check_transcript_orphans",
        description=(
            "Report chat_sessions rows whose owner has no profiles row. "
            "Read-only: this script never deletes anything."
        ),
        epilog=_CAVEAT,
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="log only on a hit, so a timer does not report on every clean run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, db: Any | None = None) -> int:
    """Entry point. Returns the process exit status (0 = no orphans).

    ``db`` is injected by the tests. Taking a client rather than patching the
    builder keeps the read path under test exactly as production runs it — the
    alternative, monkeypatching ``_build_db``, proves only that the mock was
    installed.
    """
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if db is None:
        try:
            db = _build_db()
        except SystemExit:
            raise
        except Exception:
            logger.exception("checker could not start")
            return 2

    try:
        orphans = _find_orphans(db)
    except Exception:
        logger.exception("checker could not read chat_sessions")
        return 2

    if not orphans:
        if not args.quiet:
            logger.info("no orphan transcripts")
        return 0

    session_ids = sorted(str(row.get("id")) for row in orphans)
    owner_ids = sorted({str(row.get("owner_id")) for row in orphans})
    logger.warning(
        "%d orphan transcript(s) across %d owner_id(s): sessions %s; owners %s. %s",
        len(orphans),
        len(owner_ids),
        session_ids,
        owner_ids,
        _CAVEAT,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
