-- Deny-by-default on chat_archive: revoke every direct privilege from
-- service_role, grant back only SELECT.
--
-- APPLIED 2026-08-21 as 20260820213833_revoke_chat_archive_direct_writes.
--
-- VERIFIED LIVE BEFORE APPLYING: service_role held INSERT, REFERENCES,
-- SELECT, TRIGGER on this table -- so the first draft's `revoke insert`
-- would have left REFERENCES and TRIGGER standing. After applying it holds
-- SELECT and nothing else, and anon/authenticated hold nothing.
--
-- VERIFIED AFTER APPLYING: chat_append_turn was round-tripped in a
-- deliberately aborted transaction (there is no delete path here any more,
-- so the only safe proof is one that never commits) and still wrote its
-- archive row plus both message rows -- archive_rows=1, message_rows=2 --
-- confirming SECURITY DEFINER bypasses these grants as designed.
--
-- Found by an external review immediately after
-- 20260820131914_chat_session_persistence.sql applied. chat_append_turn is
-- SECURITY DEFINER, so it runs with the privileges of the function OWNER, not
-- the caller — it never needed service_role to hold INSERT on chat_archive to
-- do its own insert there. That grant is therefore not what makes
-- chat_append_turn work; it is a SECOND, unguarded way for anything holding
-- the service-role key (SupabaseAdminClient — "SERVER-SIDE ONLY", used
-- broadly for admin operations elsewhere in this app) to write a row into
-- chat_archive directly, skipping chat_append_turn's owner/session validation
-- and its atomic pairing with a real chat_messages turn.
--
-- Nothing in this codebase currently does that — chat_archive appears nowhere
-- outside web/services/chat_store.py — so this closes a least-privilege gap,
-- not an active exploit.
--
-- WHY `revoke all` AND NOT `revoke insert`. The first draft of this file named
-- one verb. That is the exact mistake the base migration warns about, twelve
-- lines above where it revokes the sibling tables: naming verbs "leaves
-- TRUNCATE, REFERENCES and TRIGGER standing, and Supabase's default table ACL
-- for service_role can include them". The base migration then applies
-- `revoke all` to chat_sessions / chat_messages / chat_message_sources and, for
-- chat_archive alone, named three verbs instead — so chat_archive is the one
-- chat table still holding whatever else its default ACL carries. A
-- `truncate public.chat_archive` through a privilege nobody thought to name
-- erases the archive just as thoroughly as a DELETE would. This finishes the
-- pattern the base migration started and described.
--
-- SELECT is granted back because it is the only privilege anything actually
-- uses, and because reads of an append-only table are the harmless half.
--
-- ON THE DELETE GRANT THE BASE MIGRATION PROMISED. Its table comment said "The
-- migration that adds admin_purge_chat_archive grants the DELETE that function
-- needs." That promise is retired here rather than kept, for two reasons. No
-- purge function is shipping: the archive is dormant — both salts are unset,
-- so archive_keys() returns (None, None) and chat_append_turn skips every
-- archive insert — and a retention path for zero rows is machinery, not
-- safety. And when a purge function does arrive it will be SECURITY DEFINER
-- like every other function here, so it will execute as its owner and will not
-- need the grant either. A standing DELETE for service_role would only ever be
-- a second, unguarded delete path bypassing that function's own refusals.
--
-- VERIFY AT APPLY TIME: re-run chat_append_turn in a rolled-back transaction
-- (as for the base migration) to confirm the archive insert inside it still
-- succeeds — it must, since SECURITY DEFINER bypasses these grants entirely.
-- If it does not, the cause is function ownership, not this revoke; correct the
-- owner rather than re-granting the writes.
revoke all on public.chat_archive from service_role;
grant select on public.chat_archive to service_role;

comment on table public.chat_archive is
  'Append-only turn archive for quality review and internal model work. '
  'Written ONLY by chat_append_turn (SECURITY DEFINER); service_role holds '
  'SELECT and nothing else. RLS enabled with no policies by design. There is '
  'no delete path: none is granted, and any future purge function will be '
  'SECURITY DEFINER and will not need one. Dormant while ARCHIVE_OWNER_SALT '
  'and ARCHIVE_SESSION_SALT are unset.';
