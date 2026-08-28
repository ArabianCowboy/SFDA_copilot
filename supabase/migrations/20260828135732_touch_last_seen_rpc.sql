-- Throttled write path for public.profile_last_seen. Called from /api/identity on the
-- service-role client only -- see docs/data-policy-decisions.md's §4, design piece 2.
-- The `on conflict ... where` clause is the entire throttle, reusing the idiom
-- 20260828001636 established: a stale-write attempt affects zero rows rather than
-- needing a second "skip this write" mechanism.
create function public.touch_last_seen(p_user_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profile_last_seen (user_id, last_seen_at)
  values (p_user_id, now())
  on conflict (user_id) do update
     set last_seen_at = excluded.last_seen_at
   where public.profile_last_seen.last_seen_at < now() - interval '1 hour';
end;
$$;

revoke all on function public.touch_last_seen(uuid) from anon, authenticated, public;
grant execute on function public.touch_last_seen(uuid) to service_role;
