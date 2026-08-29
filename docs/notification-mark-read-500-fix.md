STATUS: HISTORICAL RECORD — fixed 2026-08-29. Kept for the diagnosis and verification trail,
not as an open task. See `docs/archive/TODO-resolved.md`'s matching entry for the short version;
`TODO.md`'s Notification Center entry links here.

# `/api/notifications/mark-read` returned 500 on every real call

## Symptom

A reader clicked a notification in the inbox (or dismissed a toast/banner, or acknowledged a
modal) and saw a generic toast: **"Could not update that notification."** Reported live, against
the real Supabase project — not `?testing=true` — with a server traceback:

```
File "web\api\app.py", line 3014, in handle_notifications_mark_read
    return _no_store(jsonify(ok=True, notification_id=notification_id, **row))
TypeError: flask.json.jsonify() got multiple values for keyword argument 'notification_id'
```

Three occurrences in one log, each on a distinct `/api/notifications/mark-read` POST, each a
plain 500 — not the intermittent `httpcore.ReadError: [WinError 10035]` Windows socket glitch
seen elsewhere in the same session's logs on unrelated routes. That similarity was this session's
first, wrong guess; the traceback is unambiguous once read.

## Root cause

`web/api/app.py`'s `handle_notifications_mark_read` built its JSON response as:

```python
row = backend.mark_read(notification_id, g.identity.user_id, action)
...
return _no_store(jsonify(ok=True, notification_id=notification_id, **row))
```

Against the **real** backend (`SupabaseNotificationBackend.mark_read`,
`web/services/notification_store.py:404-413`), `row` is the RPC's own return value:

```python
response = self._client.rpc(
    "notifications_mark_read",
    {"p_notification_id": notification_id, "p_user_id": user_id, "p_action": action},
).execute()
return getattr(response, "data", None) or {}
```

`notifications_mark_read` (`supabase/migrations/20260828001731_receipt_writes_respect_the_notification_lifecycle.sql`)
ends with `returning * into v_row; return to_jsonb(v_row);` — `v_row` is a full
`public.user_notification_reads%rowtype`, and that table's own first column (after its surrogate
`id`) is `notification_id`. So `row` already contains a `notification_id` key, and
`jsonify(ok=True, notification_id=notification_id, **row)` passes it twice — once as an explicit
keyword, once via `**row` — which Python rejects with exactly the `TypeError` in the traceback
above. **This was unconditional: every real call to this route, for every reader, for every
action, failed.**

## Why the test suite never caught it

`web/tests/test_notifications_api.py` exercises this route under `FLASK_TESTING`, against
`InMemoryNotificationBackend` (`notification_store.py`, the in-memory double the module's own
docstring says exists specifically to "mirror the real RPC's checks"). Its `mark_read` returned:

```python
read.setdefault(key, now_iso)
return dict(read)
```

`read` is a plain dict keyed only on `served_at`/`read_at`/`dismissed_at`/`acknowledged_at` — it
never carried a `notification_id` key, so the double's `row` never collided with the route's
explicit `notification_id=notification_id` keyword. All three tests that POST to this route
(`test_the_actual_recipient_can_mark_it_read`,
`test_an_all_targeted_notification_can_be_marked_by_any_reader`,
`test_a_withdrawn_notification_can_still_be_marked_read`) passed, every time, against genuinely
broken production code — because the double's _shape_, not its behaviour, diverged from the real
RPC's. `CLAUDE.md`'s standing rule — "a test that mocks the function under test proves nothing" —
is usually read as a warning about _behaviour_ mocking; this is the same failure mode one level
up, in the _shape_ of a mocked return value.

## The fix

Two changes, both required — one fixes the crash, the other makes the test suite able to catch
this class of bug again in the future:

**1. `web/api/app.py` — build the response defensively.**

```python
payload = dict(row)
payload["notification_id"] = notification_id
payload["ok"] = True
return _no_store(jsonify(payload))
```

`notification_id` is always the requested one, whether or not the backend's row already carries
that key. No behaviour change for a caller that was working before.

**2. `web/services/notification_store.py` — make the double's shape match the real RPC's.**

```python
read.setdefault(key, now_iso)
return {"notification_id": notification_id, "user_id": user_id, **read}
```

Mirrors `notifications_mark_read`'s actual return columns, so a future Flask-side bug that only
collides against `notification_id` or `user_id` fails a test instead of only showing up against
the real database.

## Verification

Fix 2 alone, with fix 1 temporarily reverted, was run against the suite first — confirming the
bug is real and the new mock shape is what actually catches it:

```
FAILED web/tests/test_notifications_api.py::test_the_actual_recipient_can_mark_it_read
FAILED web/tests/test_notifications_api.py::test_an_all_targeted_notification_can_be_marked_by_any_reader
FAILED web/tests/test_notifications_api.py::test_a_withdrawn_notification_can_still_be_marked_read
3 failed, 4 passed, 15 deselected
```

The failure is the identical `TypeError: flask.json.jsonify() got multiple values for keyword
argument 'notification_id'` the reader hit live. With both fixes applied:

```
web/tests/test_notifications_api.py web/tests/test_admin_notifications.py
web/tests/test_notification_fanout_pagination.py — 77 passed
python -m pytest -m "not browser and not integration" — 864 passed, 1 skipped
```

## What this disturbed

Nothing outside the two files above. No schema change, no migration, no i18n change, no CSS/JS
touched (so no `ASSET_VERSION` bump). The three-test regression coverage above is what protects
this route now; no new test file was added, since the existing tests became meaningful once the
double's shape was corrected.

## Confirmed live, 2026-08-29, same day

The operator restarted the local server after the fix and re-tested against the real Supabase
project: clicking a notification, dismissing a toast/banner, acknowledging a modal, and "Mark
all as read" from the bell inbox. Server log shows four `POST /api/notifications/mark-read` and
one `POST /api/notifications/mark-all-read`, all `200` — no further `TypeError`. Screenshots
confirm the toast, banner, modal acknowledgement, and inbox list all render and update correctly.
The only errors left in that log are unrelated `httpcore.ReadError: [WinError 10035]` tracebacks
on other routes (`/api/notifications/active`, `/api/identity`, `touch_last_seen`) — the same
transient Windows non-blocking-socket glitch documented elsewhere in this session, self-resolving
on retry, not a Notification Center defect.

## What this does not cover

This fix is scoped to the `notification_id` collision. It does not re-verify the Realtime
private-channel push path or the sign-out/reauthenticate flows — see `TODO.md`'s Notification
Center entry for what is still owed there.
