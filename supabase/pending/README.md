STATUS: CURRENT AUTHORITY — the apply runbook for the batch sitting in this directory.
Delete this file when `pending/` is empty. Written 2026-09-18.

# Account & Trust — the apply runbook

Fourteen migrations, written 2026-09-18, implementing the plan archived at
[`docs/archive/2026-09-18_account-and-trust.md`](../../docs/archive/2026-09-18_account-and-trust.md).
Read that for _why_, and this file for _in what order_.

**`01` and `02` were applied on 2026-09-19 and have moved to `../migrations/`. Twelve remain
here, applied to nothing.** The ordinals left behind are deliberately NOT renumbered: the file
headers and the table below cross-reference them ("must land after 08"), and renaming to close
the gap would break every one of those references.

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

| #      | File                                                                  | Gate before applying                                                                                                                                                                                                                                                                                                                                                                                  |
| ------ | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ~~01~~ | ~~`update_own_marketing_consent`~~                                    | **APPLIED 2026-09-19** → `20260918232554`                                                                                                                                                                                                                                                                                                                                                             |
| ~~02~~ | ~~`grant_marketing_consent`~~                                         | **APPLIED 2026-09-19** → `20260918232611`                                                                                                                                                                                                                                                                                                                                                             |
| —      | **deploy the application code**                                       | **01 and 02 must be live first. The deletion UI and privacy promise ship in this deploy but DARK: `account_deletion_self_serve_enabled` stays `false`, so the routes 404, the card does not render, and `/privacy` keeps the pre-self-serve wording**                                                                                                                                                 |
| —      | **verify the consent toggle, both ways**                              | withdraw _and_ grant, in a browser, before the revoke                                                                                                                                                                                                                                                                                                                                                 |
| 03     | `revoke_consent_column_grants`                                        | the step above passed                                                                                                                                                                                                                                                                                                                                                                                 |
| 04     | `freeze_profiles_update_policy`                                       | 03 applied                                                                                                                                                                                                                                                                                                                                                                                            |
| 05     | `gate_update_own_preferences`                                         | apply with 04 — 04 alone closes one of two doors                                                                                                                                                                                                                                                                                                                                                      |
| 06     | `fk_set_null_on_admin_attribution`                                    | **backup taken; restore rehearsed.** Destructive DDL                                                                                                                                                                                                                                                                                                                                                  |
| 07     | `account_deletions`                                                   | 06 applied                                                                                                                                                                                                                                                                                                                                                                                            |
| 08     | `pending_folds_into_is_active_account`                                | 07 applied. Slice 2c SPLIT this file's one predicate into two: `account_deletion_is_live` (every non-terminal state — kept by 12 and 14, including for `pending`) and `account_deletion_freezes_writes` (`purging`/`auth_delete_begun`/`failed`/`completed`). `is_active_account()` calls the NARROW one, so `pending` passes every gate again — chat, profile and preferences all work during grace. |
| 09     | `account_deletion_is_pending`                                         | 08 applied                                                                                                                                                                                                                                                                                                                                                                                            |
| 10     | `account_deletion_saga_rpcs`                                          | 07–09 applied                                                                                                                                                                                                                                                                                                                                                                                         |
| 11     | `chat_append_turn_refuses_a_pending_owner`                            | 10 applied. Slice 2c repointed its three checks at `account_deletion_freezes_writes`: a `pending` turn is filed normally, only a purging/failed one is refused. The filename is the draft label, not the contract — the header states the revised rule.                                                                                                                                               |
| 12     | `admin_set_user_flags_refuses_a_pending…`                             | 10 applied                                                                                                                                                                                                                                                                                                                                                                                            |
| 14     | `grant_marketing_consent_refuses_a_live_saga`                         | 08 applied. **Must not be skipped** — see below                                                                                                                                                                                                                                                                                                                                                       |
| —      | **install the reconcile timer**                                       | `deploy/sfda-copilot-deletion-reconcile.{service,timer}` — without it, "deletion in progress" is a promise nothing drives                                                                                                                                                                                                                                                                             |
| —      | **flip `account_deletion_self_serve_enabled` to `true`, then verify** | **the timer above is installed and has ticked once.** Request a deletion on a throwaway account, watch the ledger row reach `pending`, cancel it, and confirm the cancel lands. Only then is the promise on `/privacy` true                                                                                                                                                                           |
| 13     | `chat_sessions_owner_fk`                                              | **PARKED.** See below                                                                                                                                                                                                                                                                                                                                                                                 |

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
