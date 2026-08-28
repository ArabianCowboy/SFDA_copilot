-- touch_last_seen(uuid) previously did `insert ... values (p_user_id, now())`, which
-- raises a foreign-key violation (23503) for a p_user_id with no matching public.profiles
-- row -- the "orphan" state this repo already models (see the test-orphan-id fixture in
-- InMemoryAdminBackend). /api/identity's try/except swallows the error, so no request
-- fails, but every single request from an orphaned account logged an exception and
-- attempted a doomed insert forever. InMemoryAdminBackend.touch_last_seen already promises
-- silent no-op for this case (web/services/admin_store.py); this migration makes the real
-- RPC match that contract instead of relying on the caller's try/except to paper over it.
--
-- `insert ... select ... from public.profiles where id = p_user_id` inserts zero rows
-- (no error) when no such profile exists, rather than attempting a row that violates the
-- FK. Same throttle predicate, otherwise unchanged.
create or replace function public.touch_last_seen(p_user_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profile_last_seen (user_id, last_seen_at)
  select p.id, now()
    from public.profiles p
   where p.id = p_user_id
  on conflict (user_id) do update
     set last_seen_at = excluded.last_seen_at
   where public.profile_last_seen.last_seen_at < now() - interval '1 hour';
end;
$$;

revoke all on function public.touch_last_seen(uuid) from anon, authenticated, public;
grant execute on function public.touch_last_seen(uuid) to service_role;
