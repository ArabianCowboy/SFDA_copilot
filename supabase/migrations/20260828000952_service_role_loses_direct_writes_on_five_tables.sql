-- Close the second write surface beside the RPCs.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 14.
--
-- WHAT WAS WRONG. Five tables let service_role write directly, around the RPCs
-- that are supposed to be their only writer:
--
--   profiles                 → ALL      notifications           → ALL
--   app_settings             → ALL      notification_recipients → ALL
--   user_notification_reads  → ALL
--
-- ALL includes TRUNCATE. RLS does not close this — service_role carries
-- rolbypassrls.
--
-- The repository already believes the tighter thing and has done it twice:
-- 20260820131914:245-251 revokes every direct service-role privilege on the
-- chat tables and re-grants only SELECT, saying at line 219 that "Supabase
-- grants service_role broad DML by default"; 20260814032139 reduces audit_log
-- to INSERT, SELECT so that even the service role cannot rewrite history. The
-- notification migrations (20260823202130, 20260823202146) and
-- 20260814022601_app_settings.sql contain no service_role line at all and
-- simply inherited the default. This is that omission, not a new policy.
--
-- WHAT IT COSTS IF IT IS WRONG. Every invariant those RPCs enforce becomes
-- optional on the direct surface: a notification with no recipient snapshot
-- and no audit row; a settings document overwritten without the audit row
-- admin_write_settings would have written; a reader's acknowledgement receipts
-- altered; role/tier/is_disabled changed on profiles without the diff-based
-- audit entry admin_set_user_flags produces. No leaked key required — an
-- ordinary regression that reaches for .table("notifications").insert(...)
-- gets there and nothing refuses it.
--
-- WHY IT IS SAFE. Every direct table call from the service-role client is a
-- read. Verified across all of web/ rather than the two modules the finding
-- cites — `.table(` appears in exactly two files, `.from_(` (the supabase-py
-- alias) appears nowhere, and there is no raw SQL and no second client:
--
--   admin_store.py:245        profiles                .select(_IDENTITY_COLUMNS)
--   admin_store.py:282        app_settings            .select("settings")
--   admin_store.py:323        audit_log               .select("*")
--   admin_store.py:402        audit_log               .insert(...)   <- the only write
--   notification_store.py:209/218/228/238  profiles   .select("id", count="exact")
--   notification_store.py:408 notification_recipients .select("user_id")
--   notification_store.py:417 profiles                .select("id")
--
-- So SELECT is retained on the three tables that are read and dropped entirely
-- on the two that are not. audit_log keeps INSERT precisely because of :402 and
-- is not touched by this migration.
--
-- SECURITY DEFINER IS UNAFFECTED. Those functions execute as their owner,
-- postgres, not as service_role — the same arrangement 20260820131914 set up
-- and verified when it revoked the chat tables.
--
-- Applied together with the default-privileges migration that precedes it: that
-- one closes tomorrow's tables, this one closes today's. Closing the future and
-- leaving the present open is the wrong order.

revoke all on public.profiles                from service_role;
grant  select on public.profiles             to   service_role;

revoke all on public.app_settings            from service_role;
grant  select on public.app_settings         to   service_role;

revoke all on public.notification_recipients from service_role;
grant  select on public.notification_recipients to service_role;

-- Read by nothing directly. Both are reached only through the reader and admin
-- RPCs, so they keep no privilege at all.
revoke all on public.notifications           from service_role;
revoke all on public.user_notification_reads from service_role;
