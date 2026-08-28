"""The broadcast audience is streamed in pages, not fetched in one response.

`recipients_for_publish` branches on `target_kind`, and BOTH branches used to
fetch the entire audience in a single PostgREST call — `all_enabled_profile_ids`
for `all`, and `recipient_ids_for` for role, tier and user targets, which is the
more common send in practice. At four accounts that was optimal. At a hundred
thousand it is a hundred-thousand-row fetch triggered by one operator click, and
the only ceiling would be whatever PostgREST's `db-max-rows` happens to be —
which, if it is set, TRUNCATES the result rather than erroring. Quietly sending
to a fraction of the intended readers is the worse of the two failures, and it
looks exactly like a successful send.

Two properties are pinned here, and the second one is the one a naive
implementation gets wrong:

1. **Every id is returned exactly once, in pages.**
2. **A short page does not end the walk.** `db-max-rows` caps a response
   server-side. If it is set below the requested page size then *every* page
   comes back short, and terminating on `len(rows) < page` would stop after the
   first one — reinstating the silent truncation, invisibly. The first version
   of this code did precisely that.

These drive `SupabaseNotificationBackend` against a stub PostgREST client rather
than the in-memory double, because the pagination being tested exists only on the
real backend. The stub models the parts the code actually depends on: `.eq()`
filters, `.order()` sorts, `.limit()` bounds the request, `.gt()` applies the
keyset cursor — and a separate, independent server cap.
"""

from __future__ import annotations

import pytest

from web.services.notification_store import _FETCH_PAGE, SupabaseNotificationBackend


class _StubQuery:
    """One PostgREST request, recorded and answered from a fixed row list.

    Deliberately not a no-op mock. `.eq()` really filters and `.order()` really
    sorts, so a backend that dropped the `notification_id` filter or the
    ordering would fail here rather than pass by accident.
    """

    def __init__(self, rows: list, column: str, calls: list, server_cap: int | None) -> None:
        self._rows = rows
        self._column = column
        self._calls = calls
        self._server_cap = server_cap
        self._filters: list = []
        self._cursor = None
        self._limit = None
        self._ordered = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def order(self, column):
        assert column == self._column
        self._ordered = True
        return self

    def limit(self, count):
        self._limit = count
        return self

    def gt(self, column, value):
        assert column == self._column
        self._cursor = value
        return self

    def execute(self):
        assert self._ordered, "a keyset walk without ORDER BY returns pages in no order"
        rows = [r for r in self._rows if all(r.get(c) == v for c, v in self._filters)]
        rows.sort(key=lambda r: (r[self._column] is None, r[self._column] or ""))
        if self._cursor is not None:
            rows = [
                r for r in rows if r[self._column] is not None and r[self._column] > self._cursor
            ]
        # The client's own limit, then the server's cap on top of it — the
        # server cap is what `db-max-rows` does and the client cannot see it.
        page = rows[: self._limit]
        if self._server_cap is not None:
            page = page[: self._server_cap]
        self._calls.append((self._cursor, len(page)))
        return type("Response", (), {"data": page})()


class _StubClient:
    def __init__(self, rows: list, column: str, server_cap: int | None = None) -> None:
        self._rows = rows
        self._column = column
        self._server_cap = server_cap
        self.calls: list = []

    def table(self, _name):
        return _StubQuery(self._rows, self._column, self.calls, self._server_cap)


def _ids(count: int) -> list:
    # Zero-padded so lexicographic ordering matches numeric ordering. The real
    # column is a uuid and the comparison is the database's; the walk only
    # requires a total order. `is_disabled` is present because the stub really
    # applies `.eq()`, so a backend that dropped that filter would fail here.
    return [{"id": f"{n:08d}", "is_disabled": False} for n in range(count)]


def _profiles_with_some_disabled(enabled: int, disabled: int) -> list:
    rows = _ids(enabled)
    rows += [{"id": f"9{n:07d}", "is_disabled": True} for n in range(disabled)]
    return rows


@pytest.mark.parametrize(
    "total", [0, 1, _FETCH_PAGE - 1, _FETCH_PAGE, _FETCH_PAGE + 1, _FETCH_PAGE * 2]
)
def test_every_enabled_profile_is_returned_exactly_once(total):
    client = _StubClient(_ids(total), "id")
    backend = SupabaseNotificationBackend(client)

    result = list(backend.all_enabled_profile_ids())

    assert result == [row["id"] for row in _ids(total)]
    assert len(result) == len(set(result)), "a page boundary duplicated an id"
    assert all(size <= _FETCH_PAGE for _, size in client.calls)


def test_disabled_accounts_are_excluded_from_an_all_targeted_send():
    """A disabled reader must not be pushed to. The filter is `.eq("is_disabled",
    False)` on the query, so it is the stub's job to apply it and this test's job
    to notice if the backend ever stops sending it."""
    client = _StubClient(_profiles_with_some_disabled(enabled=_FETCH_PAGE + 3, disabled=20), "id")
    backend = SupabaseNotificationBackend(client)

    result = list(backend.all_enabled_profile_ids())

    assert result == [row["id"] for row in _ids(_FETCH_PAGE + 3)]
    assert not any(r.startswith("9") for r in result), "a disabled account was included"


def test_the_walk_is_lazy_and_does_not_fetch_until_consumed():
    """The generator is what bounds memory. If it eagerly built a list, a
    broadcast to a large audience would hold the whole audience regardless of
    how the caller chunks it — which is what the first version of this did while
    its own comment claimed otherwise."""
    client = _StubClient(_ids(_FETCH_PAGE * 2), "id")
    backend = SupabaseNotificationBackend(client)

    walk = backend.all_enabled_profile_ids()
    assert client.calls == [], "the audience was fetched before anything consumed it"

    next(iter(walk))
    assert len(client.calls) == 1, "consuming one id should cost exactly one page"


@pytest.mark.parametrize("server_cap", [1, 7, _FETCH_PAGE // 2])
def test_a_server_row_cap_below_the_page_size_does_not_truncate_the_audience(server_cap):
    """The failure this whole method exists to prevent.

    PostgREST's `db-max-rows` caps every response server-side. With a cap below
    the requested page size, EVERY page comes back short — so a walk that stops
    on a short page delivers `server_cap` recipients out of however many there
    are and reports success. The loop must continue until a page is genuinely
    empty.
    """
    total = _FETCH_PAGE + 13
    client = _StubClient(_ids(total), "id", server_cap=server_cap)
    backend = SupabaseNotificationBackend(client)

    result = list(backend.all_enabled_profile_ids())

    assert result == [row["id"] for row in _ids(total)], (
        f"a server cap of {server_cap} truncated the audience to {len(result)} of {total}"
    )


def test_recipient_ids_are_paged_and_filtered_to_one_notification():
    rows = [{"user_id": f"{n:08d}", "notification_id": "wanted"} for n in range(_FETCH_PAGE + 7)]
    rows += [{"user_id": f"9{n:07d}", "notification_id": "other"} for n in range(50)]
    client = _StubClient(rows, "user_id")
    backend = SupabaseNotificationBackend(client)

    result = list(backend.recipient_ids_for("wanted"))

    assert result == [f"{n:08d}" for n in range(_FETCH_PAGE + 7)]
    assert not any(r.startswith("9") for r in result), "another notification's recipients leaked in"


def test_a_null_key_in_the_last_row_of_a_page_stops_rather_than_loops():
    """`notification_recipients.user_id` is NULLABLE — the FK is
    `on delete set null`, which is the deliberate reader-anonymisation design in
    20260823202146. So a null key is reachable here, not merely defensive.

    A null cannot advance the cursor. Stopping is the only correct option:
    continuing would re-request the same page forever, and skipping past it would
    need an ordering that null keys do not have. This pins the termination, not
    the completeness — a partial audience is bad and an unkillable request loop
    inside an admin route is worse.
    """
    rows = [{"user_id": f"{n:08d}", "notification_id": "any"} for n in range(_FETCH_PAGE - 1)] + [
        {"user_id": None, "notification_id": "any"}
    ]
    client = _StubClient(rows, "user_id")
    backend = SupabaseNotificationBackend(client)

    result = list(backend.recipient_ids_for("any"))

    assert len(result) == _FETCH_PAGE - 1
    assert len(client.calls) == 1
