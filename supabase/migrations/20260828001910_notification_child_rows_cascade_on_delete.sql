-- Stop holding a delete-ordering invariant inside one function body.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 9.
--
-- notification_recipients.notification_id and
-- user_notification_reads.notification_id both referenced notifications(id)
-- with no ON DELETE action, so both were NO ACTION. admin_purge_notification
-- deletes the children first, in the same transaction, and is correct — but
-- that ordering was an invariant held only inside that one function body. Any
-- future DELETE FROM notifications — a manual cleanup, a retention job, a
-- second purge path — got 23503 instead of doing the right thing.
--
-- The sibling case was already fixed once for exactly this reason:
-- 20260825001815 exists because notifications.resend_of had the same problem
-- and rejected a purge outright. These two were not included then.
--
-- CASCADE IS CORRECT HERE AND WRONG FOR chat_sessions.owner_id (plan finding
-- 5), and the difference is worth stating so the two are not read as
-- inconsistent: a notification is operator-owned and its receipts are
-- meaningless without it, whereas a conversation is reader-owned and outlives
-- the account by design.
--
-- BOTH user_id FKs ARE LEFT EXACTLY AS THEY ARE — on delete set null. That is
-- deliberate reader anonymisation, the surrogate keys are what make the
-- nulling legal, and 20260823202146 says so.
--
-- admin_purge_notification's explicit child deletes stay. They are now
-- redundant rather than load-bearing, and removing them would be a second
-- concern in a migration that is about the constraint.
--
-- Drop-and-add in one file because an ON DELETE action cannot be altered in
-- place. apply_migration wraps the file in one transaction, so there is no
-- instant at which the referential integrity is unguarded. Existing rows are
-- re-scanned by the ADD, which at zero rows costs nothing.

alter table public.notification_recipients
  drop constraint notification_recipients_notification_id_fkey,
  add  constraint notification_recipients_notification_id_fkey
    foreign key (notification_id) references public.notifications(id) on delete cascade;

alter table public.user_notification_reads
  drop constraint user_notification_reads_notification_id_fkey,
  add  constraint user_notification_reads_notification_id_fkey
    foreign key (notification_id) references public.notifications(id) on delete cascade;
