STATUS: CURRENT AUTHORITY — the apply runbook for the batch sitting in this directory.
Delete this file when `pending/` is empty. Written 2026-09-18.

# Account & Trust — the apply runbook

Fifteen migrations implementing the plan archived at
[`docs/archive/2026-09-18_account-and-trust.md`](../../docs/archive/2026-09-18_account-and-trust.md).
Read that for _why_, and this file for _in what order_. (Fourteen were written 2026-09-18;
`15` was added 2026-09-19 to close a defect the step-up design created — see below.)

**FOURTEEN of the fifteen were applied on 2026-09-19 and have moved to `../migrations/`.
ONE remains here: `13`, parked** until one real deletion completes end to end — see below.

The code deploy that gated `03`-`05` landed on 2026-09-19: `account-and-trust` at `33b15c1`,
Python 3.10.12 on the VPS, service healthy, and the consent toggle verified in both
directions before the revoke.

**A backup was NOT taken before `06`.** The operator decided to proceed without one on
2026-09-19. Recorded here rather than quietly omitted: no migration in this batch deletes a
row — `06` drops and re-adds two foreign keys, and everything else creates tables, functions
and guards — so the exposure was bounded, but the runbook's own gate was skipped and a reader
of this file should know that.

The ordinals left behind are deliberately NOT renumbered: the file headers cross-reference
them ("must land after 08"), and renaming to close the gap would break those references.

The convention these files follow — ordinal names, and why an ordinal is deliberately not a
version — is in [`supabase/README.md`](../README.md#supabasepending--migrations-written-but-not-yet-applied).

## Before anything

1. **Confirm the backup schedule and run one restore rehearsal.** `docs/OPERATIONS.md`
   records no retention period, and `06` and `13` are destructive DDL. This is a hard gate on
   `06` onward, not a nicety.
2. Take a backup immediately before `06`.
3. ~~**Count the rows in `chat_archive` and confirm it is empty.**~~ **DONE 2026-09-19:
   `select count(*) from public.chat_archive` returned 0** against the live project. The
   privacy copy's archive-excluded disclosure ("the dormant research archive collects nothing
   while its salts are unset") is therefore true of production and not only of the design.
   Re-check only if a salt is ever set — which `_refuse_if_archive_has_no_purge_path` now
   refuses to let happen silently.
4. Have `supabase/tests/` ready to run by hand — it is not in CI
   (`docs/ARCHITECTURE.md:507`), so it is a release-checklist item.

## The order, and what each step is gated on

| #      | File                                                                      | Gate before applying                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------ | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ~~01~~ | ~~`update_own_marketing_consent`~~                                        | **APPLIED 2026-09-19** → `20260918232554`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~02~~ | ~~`grant_marketing_consent`~~                                             | **APPLIED 2026-09-19** → `20260918232611`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~—~~  | ~~**deploy the application code**~~                                       | **DONE 2026-09-19** — `account-and-trust` @ `33b15c1` on the VPS, Python 3.10.12, service healthy                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ~~—~~  | ~~**verify the consent toggle, both ways**~~                              | **DONE 2026-09-19** — withdraw goes to the RPC, grant to the Flask route; no consent column is sent by the browser at all                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~03~~ | ~~`revoke_consent_column_grants`~~                                        | **APPLIED 2026-09-19** → `20260919013741`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~04~~ | ~~`freeze_profiles_update_policy`~~                                       | **APPLIED 2026-09-19** → `20260919013800`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~05~~ | ~~`gate_update_own_preferences`~~                                         | **APPLIED 2026-09-19** → `20260919013813`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~06~~ | ~~`fk_set_null_on_admin_attribution`~~                                    | **APPLIED 2026-09-19** → `20260918234327`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~07~~ | ~~`account_deletions`~~                                                   | **APPLIED 2026-09-19** → `20260918234351`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~08~~ | ~~`pending_folds_into_is_active_account`~~                                | **APPLIED 2026-09-19** → `20260918234407`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~09~~ | ~~`account_deletion_is_pending`~~                                         | **APPLIED 2026-09-19** → `20260918234427`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~10~~ | ~~`account_deletion_saga_rpcs`~~                                          | **APPLIED 2026-09-19** → `20260918234525`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~11~~ | ~~`chat_append_turn_refuses_a_pending_owner`~~                            | **APPLIED 2026-09-19** → `20260918234615`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~12~~ | ~~`admin_set_user_flags_refuses_a_pending…`~~                             | **APPLIED 2026-09-19** → `20260918234710`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~14~~ | ~~`grant_marketing_consent_refuses_a_live_saga`~~                         | **APPLIED 2026-09-19** → `20260918234722`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ~~—~~  | ~~**install the reconcile timer**~~                                       | **DONE 2026-09-19** — units installed, ran once by hand (exit 0, nothing due), timer enabled                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ~~—~~  | ~~**flip `account_deletion_self_serve_enabled` to `true`, then verify**~~ | **DONE 2026-09-19.** Flipped (`3558e04`) once the gate was met — timer installed, enabled and ticking, `15` applied. **Round trip verified the same day against production:** request → ledger row `pending`, `grace_until` exactly +30 days, chat still usable during grace, cancel → `cancelled`, banner gone and still gone after a reload. Confirmed in the database, not only in the UI: one row for `d216e1d3`, `state = cancelled`, no `transcripts_purged_at`, no `auth_delete_begun_at`, `attempt_count = 0`, `last_error_code` null. `auth.sessions` also confirmed the request's global sign-out landed — every session predating it was gone |
| ~~15~~ | ~~`step_up_attempts`~~                                                    | **APPLIED 2026-09-19** → `20260918234736`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 13     | `chat_sessions_owner_fk`                                                  | **PARKED.** See below                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

**Why the code deploy sits between 02 and 03.** `03` revokes the direct column grants the
browser used to write consent through. Applied before the repointed toggle is live, consent
withdrawal breaks silently for every reader. Applied after, the revoke is what makes the
RPC's validation unbypassable. If `main` is the branch the VPS pulls, keep this batch on a
feature branch until the order above can be followed.

**Why the deletion switch stays OFF until the timer.** The code deploy between `02`
and `03` necessarily carries the deletion UI and the rewritten privacy copy with it —
there is one deploy, not two. If the switch flipped with that deploy, the copy would
claim "you can delete your entire account yourself" while `07`–`14` are unapplied and
both deletion routes answer 503 — and again between `10` and the timer install, when
requests are accepted and nothing drives them. The repo rule is "ship the feature
before the sentence that promises it" (CLAUDE.md), so the sentence ships dark: the
switch is its own explicit step above, after the timer, with a throwaway-account
round trip as its gate. Both retention wordings stay in the catalogues — one is true
before the switch, the other after — rather than one overwriting the other.

**Why 14 exists and is out of numeric order.** `02` ships the consent-grant RPC with no
active-account check, on the reasoning that its Flask route's `_gate` refuses a disabled
account. That is true of `disabled` and false of `deletion_pending` — which is never
`is_disabled`, deliberately, so its cancel path stays reachable. Without `14`, a reader inside
the grace window could opt _into_ marketing. Slice 2c unfroze the rest of grace (chat,
profile, preferences all work while `pending`) and kept exactly this refusal: collecting a
fresh marketing permission from someone who has asked to be erased is the one thing a
grace window must still refuse. `14` cannot be folded
into `02` because the predicate it needs, `account_deletion_is_live()`, does not exist until
`08`. Skipping it leaves the hole open the moment `07` makes a saga row possible.

**Why 15 is in this batch at all.** It is not part of the deletion design; it closes a defect
the deletion design created. Step-up re-authentication verifies the reader's password by
calling GoTrue from this host's single address, which blinds GoTrue's own per-IP limiter — the
exact reason `POST /auth/login` was retired. The Flask limit that was supposed to bound it is
`memory://` and resets on every worker recycle, and `--max-requests 1000` makes those routine.
`15` puts the throttle in the database instead. It has no dependency on `03`-`14`, but the
feature switch must not be flipped without it.

**Why 13 is parked.** It adds `chat_sessions.owner_id → auth.users ON DELETE RESTRICT`. Until
one real deletion has completed end to end, applying it converts a saga bug into a `23503`
that blocks deletion entirely. Run its orphan check first; any hit is an incident, not a row
to force.

## After each apply

The filename rule's fourth step is mandatory, not a tidy-up: read the real version back from
`list_migrations`, then `git mv` the file into `../migrations/` under exactly that name.

## After the batch

- Re-run the Supabase advisors and `supabase/tests/` (including the two new files,
  `disabled_consent.test.sql` and `account_deletion.test.sql`, which pass only once these are
  applied).
- Delete this file.
