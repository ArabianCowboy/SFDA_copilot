-- A disabled account keeps full PostgREST access to its own chat data.
--
-- WHY
-- ---
-- Setting profiles.is_disabled = true only gates Flask endpoints
-- (@auth_required / _authenticate_request). The browser talks directly to
-- PostgREST for RLS-governed tables, so a disabled reader holding a live JWT
-- can still SELECT and DELETE their own transcripts, bypassing Flask
-- entirely. No RLS policy on chat_sessions, chat_messages or
-- chat_message_sources currently checks is_disabled
-- (20260820131914_chat_session_persistence.sql:177-201 --
-- using (owner_id = (select auth.uid())), nothing more).
--
-- This is also the second argument for is_active_account() beyond this
-- migration: Supabase's own docs are explicit that access-token revocation on
-- sign-out is not instant -- a token stays valid until its exp claim, so
-- disabling an account and revoking its sessions still leaves a window where
-- only the row policy closes the gap.
--
-- is_active_account() is wrapped as (select public.is_active_account()) in
-- every USING clause, matching this file's own existing (select auth.uid())
-- idiom, so the planner evaluates it once per statement rather than once per
-- row (initplan).
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction (20260814005509...sql:35-43).

create or replace function public.is_active_account()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.profiles
     where id = (select auth.uid())
       and is_disabled = false
  );
$$;

revoke execute on function public.is_active_account() from anon, public;
grant execute on function public.is_active_account() to authenticated;

-- ---------------------------------------------------------------------------
-- chat_sessions: select and delete.
-- ---------------------------------------------------------------------------
drop policy if exists chat_sessions_select_own on public.chat_sessions;
create policy chat_sessions_select_own on public.chat_sessions
  for select to authenticated
  using (owner_id = (select auth.uid()) and (select public.is_active_account()));

drop policy if exists chat_sessions_delete_own on public.chat_sessions;
create policy chat_sessions_delete_own on public.chat_sessions
  for delete to authenticated
  using (owner_id = (select auth.uid()) and (select public.is_active_account()));

-- ---------------------------------------------------------------------------
-- chat_messages: select only (no insert/update policy exists, by design --
-- see chat_session_persistence.sql's "TWO ACCESS PATTERNS" comment).
-- ---------------------------------------------------------------------------
drop policy if exists chat_messages_select_own on public.chat_messages;
create policy chat_messages_select_own on public.chat_messages
  for select to authenticated
  using (owner_id = (select auth.uid()) and (select public.is_active_account()));

-- ---------------------------------------------------------------------------
-- chat_message_sources: select only, via its parent message's ownership.
-- ---------------------------------------------------------------------------
drop policy if exists chat_message_sources_select_own on public.chat_message_sources;
create policy chat_message_sources_select_own on public.chat_message_sources
  for select to authenticated
  using (
    (select public.is_active_account())
    and exists (
      select 1 from public.chat_messages m
       where m.id = chat_message_sources.message_id
         and m.owner_id = (select auth.uid())
    )
  );
