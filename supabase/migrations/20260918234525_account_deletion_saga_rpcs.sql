-- The deletion saga steps: request, claim, purge, auth-delete, complete,
-- fail, cancel. Slice 2a of docs/account-and-trust-plan.md §3-M5.
--
-- FULL STANDARD CONTRACT ON EVERY FUNCTION, NO NEW EXEMPTION:
-- `security definer` + `search_path = ''` + revoked from
-- `anon, authenticated, public` + granted to `service_role` only +
-- `p_owner_id` first and filtered on inside. The Flask driver and the
-- systemd timer (slice 2b) call these over PostgREST with the service key;
-- nothing here is browser-reachable.
--
-- WHAT EACH FUNCTION DOES, AND THE ORDER THE DRIVER CALLS THEM:
--
--   1. account_deletion_request(p_owner_id) — insert the saga row in
--      `pending`, grace 30 days. REFUSES an administrator target (D1's
--      carve-out, enforced HERE in the body, not only in Flask): an admin
--      leaving is an operator action. Idempotent: a second request for a
--      live-or-failed saga returns the existing row with `'_replay': true`
--      rather than raising or duplicating (the admin_create_notification
--      replay shape). A request after a `cancelled` row re-opens grace with
--      fresh timestamps; a request against `completed` raises DL004 — the
--      account is gone, so a request for it is a bug.
--   2. account_deletion_claim(p_owner_id, p_from_state, p_lease_seconds) —
--      move a due row INTO `purging` and hold a lease on it. The only edges
--      are pending→purging (requires purge_after <= now(), i.e. grace over),
--      failed→purging (retry), and purging→purging (re-claim after the lease
--      expired; the purge is idempotent). Anything else raises DL004.
--      Returns the row, or NULL when there is nothing to claim — someone
--      else holds the lease or the row is not due — which is a NORMAL
--      outcome, not an error. Note the predicate is `lease_until is null or
--      lease_until < now()`: a bare `lease_until < now()` never matches a
--      fresh row, whose lease is null.
--   3. account_deletion_purge_transcripts(p_owner_id) — delete
--      `chat_sessions` by owner_id (one statement; `chat_messages` and
--      `chat_message_sources` cascade off it through
--      chat_messages_session_owner_fk). Requires state `purging` with a live
--      lease, so two drivers under `--threads 8` cannot purge twice.
--   4. account_deletion_begin_auth_delete(p_owner_id) — RE-PURGE inside the
--      step that moves the saga to `auth_delete_begun`, closing the 300s
--      in-flight-stream window (a stream admitted just before the first
--      purge can write its turn after it; `chat_append_turn` refuses a
--      frozen owner from 11 on — `purging` and beyond, not `pending`, per
--      slice 2c — but a turn admitted before the request still lands).
--      Renews the lease for the outbound GoTrue call.
--   5. account_deletion_record_auth_outcome(p_owner_id, p_outcome,
--      p_error_code) — record what GoTrue said. `deleted` and `not_found`
--      both mark auth_deleted_at: GoTrue's `user_not_found` (which
--      classify_admin_failure maps to the definitive `no_such_account`,
--      web/services/auth_admin.py:74-77) is SUCCESS here, not failure — the
--      user is gone, which is the goal; letting it flip a completed saga to
--      failed would be the exact inversion. `failed` moves to `failed` with
--      the CODE (never a message). `ambiguous` keeps the state and re-arms
--      next_attempt_at. Serialized by STATE, not by lease: no claim edge
--      leaves `auth_delete_begun`, so no second driver can interleave.
--   6. account_deletion_complete(p_owner_id) — requires `auth_delete_begun`
--      with auth_deleted_at set, AND refuses DL006 while the profile row
--      still exists: completion must never be recorded while PII remains
--      (fail closed — the GoTrue delete cascades the profile row, so a
--      surviving row means the delete did not happen).
--   7. account_deletion_fail(p_owner_id, p_error_code) — any non-terminal
--      state to `failed`, clearing the lease so a driver can reclaim.
--   8. account_deletion_cancel(p_owner_id) — legal from `pending`, and from
--      `failed` only when transcripts_purged_at is null (nothing destroyed
--      yet); otherwise DL005 — cancelling past the purge would be a lie,
--      there is nothing truthful left to cancel back to. Cancel restores
--      EXACTLY what the saga changed and nothing else: the saga changes NO
--      `profiles` column (pending is its own state — the constraint brief),
--      so cancel touches only the ledger row and MUST NOT clear `is_disabled`
--      flags an operator set independently (regression-asserted in
--      supabase/tests/account_deletion.test.sql).
--
-- WHAT INTERRUPTION LEAVES BEHIND. Steps 1-4 and 7-8 are single statements
-- inside one transaction each: they commit or they roll back, nothing
-- half-done. The un-reconcilable step is 5's `ambiguous`: the GoTrue call
-- committed server-side or it did not, and this database cannot know. The
-- reconciliation rule (plan §5) is: GoTrue admin get-by-id no longer
-- returning the user means success, whatever the transport said — evaluated
-- in Python (service_role reaches auth.users nowhere, supabase/README.md),
-- never here.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name.

-- ---------------------------------------------------------------------------
-- 1. Request.
-- ---------------------------------------------------------------------------
create function public.account_deletion_request(p_owner_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_role  text;
  v_row   public.account_deletions%rowtype;
  v_grace timestamptz;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;

  -- Owner-filtered: the caller is the service role, so auth.uid() is
  -- meaningless here and p_owner_id is the only ownership boundary.
  select p.role into v_role from public.profiles p where p.id = p_owner_id;
  if v_role is null then
    raise exception 'no profile row for %', p_owner_id using errcode = 'P0002';
  end if;

  -- D1's carve-out, enforced in the body: self-serve deletion is refused for
  -- administrators. An administrator leaving is an operator action.
  if v_role = 'admin' then
    raise exception 'self-serve deletion is not available to administrators'
      using errcode = 'DL003';
  end if;

  select * into v_row from public.account_deletions d where d.user_id = p_owner_id;

  if v_row.user_id is not null then
    if v_row.state = 'completed' then
      raise exception 'this account is already deleted' using errcode = 'DL004';
    end if;

    if v_row.state = 'cancelled' then
      -- A reader who cancelled and changes their mind gets a fresh grace
      -- window, not a resurrection of the old one.
      v_grace := now() + interval '30 days';
      update public.account_deletions
         set state = 'pending',
             requested_at = now(),
             grace_until = v_grace,
             purge_after = v_grace,
             next_attempt_at = v_grace,
             attempt_count = 0,
             lease_until = null,
             transcripts_purged_at = null,
             auth_delete_begun_at = null,
             auth_deleted_at = null,
             completed_at = null,
             last_error_code = null
       where user_id = p_owner_id
      returning * into v_row;
      return to_jsonb(v_row);
    end if;

    -- Live or failed: idempotent replay, not a duplicate.
    return to_jsonb(v_row) || jsonb_build_object('_replay', true);
  end if;

  v_grace := now() + interval '30 days';
  insert into public.account_deletions (
    user_id, state, requested_at, grace_until, purge_after, next_attempt_at
  )
  values (p_owner_id, 'pending', now(), v_grace, v_grace, v_grace)
  returning * into v_row;

  return to_jsonb(v_row) || jsonb_build_object('_replay', false);
end;
$$;

revoke execute on function public.account_deletion_request(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_request(uuid)
  to service_role;

-- ---------------------------------------------------------------------------
-- 2. Claim into purging.
-- ---------------------------------------------------------------------------
create function public.account_deletion_claim(
  p_owner_id uuid, p_from_state text, p_lease_seconds integer default 300
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row public.account_deletions%rowtype;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;
  if p_from_state not in ('pending', 'failed', 'purging') then
    raise exception 'a saga can only be claimed from pending, failed or purging'
      using errcode = 'DL004';
  end if;
  if p_lease_seconds is null or p_lease_seconds <= 0 then
    raise exception 'a positive lease window is required' using errcode = '22023';
  end if;

  -- One statement: claim and move, or match nothing. `lease_until is null`
  -- is the fresh-row arm — without it a never-claimed row is unclaimable.
  -- `purging → purging` is the expired-lease re-claim; the other two edges
  -- additionally require a free lease so a live claim is never stolen.
  update public.account_deletions d
     set state = 'purging',
         attempt_count = d.attempt_count + 1,
         lease_until = now() + (p_lease_seconds || ' seconds')::interval,
         next_attempt_at = now() + (p_lease_seconds || ' seconds')::interval
   where d.user_id = p_owner_id
     and d.state = p_from_state
     and (d.lease_until is null or d.lease_until < now())
     and (p_from_state <> 'pending' or d.purge_after <= now())
  returning * into v_row;

  -- No row is a normal outcome (held elsewhere, or not due), not an error.
  if v_row.user_id is null then
    return null;
  end if;
  return to_jsonb(v_row);
end;
$$;

revoke execute on function public.account_deletion_claim(uuid, text, integer)
  from anon, authenticated, public;
grant execute on function public.account_deletion_claim(uuid, text, integer)
  to service_role;

-- ---------------------------------------------------------------------------
-- 3. Purge transcripts.
-- ---------------------------------------------------------------------------
create function public.account_deletion_purge_transcripts(p_owner_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row   public.account_deletions%rowtype;
  v_count integer;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;

  -- The lease is the lock: only the driver holding it may purge.
  select * into v_row
    from public.account_deletions d
   where d.user_id = p_owner_id
     and d.state = 'purging'
     and d.lease_until is not null and d.lease_until > now()
     for update;

  if v_row.user_id is null then
    raise exception 'no claimed purging saga for %', p_owner_id using errcode = 'DL004';
  end if;

  -- One statement. chat_messages and chat_message_sources cascade off
  -- chat_sessions through chat_messages_session_owner_fk.
  delete from public.chat_sessions s where s.owner_id = p_owner_id;
  get diagnostics v_count = row_count;

  update public.account_deletions
     set transcripts_purged_at = coalesce(transcripts_purged_at, now()),
         next_attempt_at = now()
   where user_id = p_owner_id
  returning * into v_row;

  return to_jsonb(v_row) || jsonb_build_object('purged_sessions', v_count);
end;
$$;

revoke execute on function public.account_deletion_purge_transcripts(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_purge_transcripts(uuid)
  to service_role;

-- ---------------------------------------------------------------------------
-- 4. Re-purge and move to auth-delete-begun.
-- ---------------------------------------------------------------------------
create function public.account_deletion_begin_auth_delete(p_owner_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row   public.account_deletions%rowtype;
  v_count integer;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;

  select * into v_row
    from public.account_deletions d
   where d.user_id = p_owner_id
     and d.state = 'purging'
     and d.lease_until is not null and d.lease_until > now()
     for update;

  if v_row.user_id is null then
    raise exception 'no claimed purging saga for %', p_owner_id using errcode = 'DL004';
  end if;

  -- The re-purge: a stream admitted just before the first purge can run up
  -- to 300s and write its turn after it (11 refuses NEW turns for a frozen
  -- owner — `purging` and beyond, not `pending`, per slice 2c — but a turn
  -- admitted before the request still lands through the lazy session
  -- create). Purging again here is what makes that window closed rather
  -- than merely narrow.
  delete from public.chat_sessions s where s.owner_id = p_owner_id;
  get diagnostics v_count = row_count;

  update public.account_deletions
     set state = 'auth_delete_begun',
         transcripts_purged_at = coalesce(transcripts_purged_at, now()),
         auth_delete_begun_at = now(),
         lease_until = now() + interval '5 minutes',
         next_attempt_at = now() + interval '5 minutes'
   where user_id = p_owner_id
  returning * into v_row;

  return to_jsonb(v_row) || jsonb_build_object('repurged_sessions', v_count);
end;
$$;

revoke execute on function public.account_deletion_begin_auth_delete(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_begin_auth_delete(uuid)
  to service_role;

-- ---------------------------------------------------------------------------
-- 5. Record the GoTrue outcome.
-- ---------------------------------------------------------------------------
create function public.account_deletion_record_auth_outcome(
  p_owner_id uuid, p_outcome text, p_error_code text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row public.account_deletions%rowtype;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;
  if p_outcome not in ('deleted', 'not_found', 'failed', 'ambiguous') then
    raise exception 'an auth outcome of deleted, not_found, failed or ambiguous is required'
      using errcode = '22023';
  end if;

  -- Serialized by state, not by lease: no claim edge leaves
  -- auth_delete_begun, so no second driver can hold this step concurrently.
  -- The lease from step 4 may have expired during a slow provider call;
  -- that does not un-claim the step.
  select * into v_row
    from public.account_deletions d
   where d.user_id = p_owner_id
     and d.state = 'auth_delete_begun'
     for update;

  if v_row.user_id is null then
    raise exception 'no auth_delete_begun saga for %', p_owner_id using errcode = 'DL004';
  end if;

  if p_outcome in ('deleted', 'not_found') then
    -- not_found IS success: GoTrue's user_not_found / no_such_account means
    -- the user is gone, which is the goal. Recording it as failure would
    -- flip a completed deletion to failed.
    update public.account_deletions
       set auth_deleted_at = now(),
           last_error_code = null,
           next_attempt_at = now()
     where user_id = p_owner_id
    returning * into v_row;
  elsif p_outcome = 'failed' then
    if p_error_code is null then
      raise exception 'a failure needs an error code, never a message'
        using errcode = '22023';
    end if;
    update public.account_deletions
       set state = 'failed',
           last_error_code = p_error_code,
           lease_until = null,
           next_attempt_at = now()
     where user_id = p_owner_id
    returning * into v_row;
  else
    -- Ambiguous: the transport failed and the provider may already have
    -- committed. State stands; the timer looks again, and the Python side
    -- reconciles through GoTrue admin get-by-id before retrying.
    update public.account_deletions
       set last_error_code = coalesce(p_error_code, 'auth_admin_unreachable'),
           next_attempt_at = now()
     where user_id = p_owner_id
    returning * into v_row;
  end if;

  return to_jsonb(v_row);
end;
$$;

revoke execute on function public.account_deletion_record_auth_outcome(uuid, text, text)
  from anon, authenticated, public;
grant execute on function public.account_deletion_record_auth_outcome(uuid, text, text)
  to service_role;

-- ---------------------------------------------------------------------------
-- 6. Complete.
-- ---------------------------------------------------------------------------
create function public.account_deletion_complete(p_owner_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row     public.account_deletions%rowtype;
  v_profile uuid;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;

  select * into v_row
    from public.account_deletions d
   where d.user_id = p_owner_id
     and d.state = 'auth_delete_begun'
     and d.auth_deleted_at is not null
     for update;

  if v_row.user_id is null then
    raise exception 'no auth-deleted saga for %', p_owner_id using errcode = 'DL004';
  end if;

  -- Fail closed: the GoTrue delete cascades the profile row (profiles_id_fkey),
  -- which in turn cascades profile_last_seen and reader_quota_overrides. A
  -- surviving profile row means the delete did not happen — recording
  -- completion now would certify an erasure that kept the PII.
  select p.id into v_profile from public.profiles p where p.id = p_owner_id;
  if v_profile is not null then
    raise exception 'the profile row for % still exists', p_owner_id using errcode = 'DL006';
  end if;

  update public.account_deletions
     set state = 'completed',
         completed_at = now(),
         lease_until = null,
         next_attempt_at = now()
   where user_id = p_owner_id
  returning * into v_row;

  return to_jsonb(v_row);
end;
$$;

revoke execute on function public.account_deletion_complete(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_complete(uuid)
  to service_role;

-- ---------------------------------------------------------------------------
-- 7. Fail.
-- ---------------------------------------------------------------------------
create function public.account_deletion_fail(p_owner_id uuid, p_error_code text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row public.account_deletions%rowtype;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;
  if p_error_code is null then
    raise exception 'a failure needs an error code, never a message'
      using errcode = '22023';
  end if;

  update public.account_deletions d
     set state = 'failed',
         last_error_code = p_error_code,
         lease_until = null,
         next_attempt_at = now()
   where d.user_id = p_owner_id
     and d.state not in ('completed', 'cancelled')
  returning * into v_row;

  if v_row.user_id is null then
    raise exception 'no live saga for %', p_owner_id using errcode = 'DL004';
  end if;

  return to_jsonb(v_row);
end;
$$;

revoke execute on function public.account_deletion_fail(uuid, text)
  from anon, authenticated, public;
grant execute on function public.account_deletion_fail(uuid, text)
  to service_role;

-- ---------------------------------------------------------------------------
-- 8. Cancel.
-- ---------------------------------------------------------------------------
create function public.account_deletion_cancel(p_owner_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row public.account_deletions%rowtype;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;

  select * into v_row
    from public.account_deletions d
   where d.user_id = p_owner_id
     and (
       d.state = 'pending'
       or (d.state = 'failed' and d.transcripts_purged_at is null)
     )
     for update;

  if v_row.user_id is null then
    raise exception 'this deletion can no longer be cancelled'
      using errcode = 'DL005';
  end if;

  -- Restore EXACTLY what the saga changed and nothing else. The saga changes
  -- no profiles column — pending is its own state, not is_disabled — so
  -- cancel touches only this ledger row. In particular it MUST NOT clear
  -- is_disabled / disabled_at / disabled_by / disabled_reason: an operator
  -- may have disabled the account independently, and "cancelling" that would
  -- be privilege escalation through the reader's own cancel path.
  update public.account_deletions
     set state = 'cancelled',
         completed_at = now(),
         lease_until = null,
         next_attempt_at = now()
   where user_id = p_owner_id
  returning * into v_row;

  return to_jsonb(v_row);
end;
$$;

revoke execute on function public.account_deletion_cancel(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_cancel(uuid)
  to service_role;
