-- Record a marketing-consent GRANT for one account, called only by Flask.
-- Slice 1 of docs/account-and-trust-plan.md §3 (decision D5: granting is the
-- Flask-mediated half of the consent carve-out; withdrawing is 01).
--
-- FULL STANDARD CONTRACT, NO NEW EXEMPTION: `security definer` +
-- `search_path = ''` + revoked from `anon, authenticated, public` + granted
-- to `service_role` only + `p_owner_id` first and filtered on inside. The
-- Flask route (`POST /account/api/consent/grant` in web/api/account.py)
-- derives the owner from `g.identity` and stamps `PRIVACY_POLICY_VERSION`
-- server-side; the caller supplies only language and surface. A disabled
-- account may never grant: that refusal comes from the route's `_gate`,
-- not from a second check here.
--
-- The row trigger `profiles_set_marketing_consent_record` still fires on
-- this write (triggers fire for every writer; only the privilege-guard
-- trigger is role-sensitive) and stamps the server-owned grant timestamps,
-- so this body validates its inputs the same way rather than leaning on a
-- 22023 from the trigger that tells the operator nothing.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name.

create function public.grant_marketing_consent(
  p_owner_id uuid, p_policy_version text, p_language text, p_surface text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_rows integer;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;

  if p_policy_version is null
     or p_policy_version is distinct from btrim(p_policy_version)
     or char_length(p_policy_version) not between 1 and 64
     -- `null not in (...)` is NULL, not true, and `false or NULL` is NULL --
     -- so without this explicit null test a null language would fall through
     -- the whole chain unraised. The trigger this mirrors
     -- (20260823014034_marketing_consent_record.sql:134) has the same gap;
     -- it is unreachable there because a null language means the row is not
     -- a grant at all, but here p_language arrives as an argument.
     or p_language is null
     or p_language not in ('en', 'ar')
     or p_surface is null
     or p_surface is distinct from btrim(p_surface)
     or char_length(p_surface) not between 1 and 32 then
    raise exception 'marketing consent requires valid policy, language and surface'
      using errcode = '22023';
  end if;

  -- Static column list, filtered on the passed-in owner: the caller is the
  -- service role, so auth.uid() is meaningless here and p_owner_id is the
  -- only ownership boundary this function has.
  update public.profiles
     set marketing_consent = true,
         marketing_consent_policy_version = p_policy_version,
         marketing_consent_language = p_language,
         marketing_consent_surface = p_surface
   where id = p_owner_id;

  get diagnostics v_rows = row_count;
  if v_rows = 0 then
    raise exception 'no profile row for %', p_owner_id using errcode = 'P0002';
  end if;
end;
$$;

revoke execute on function public.grant_marketing_consent(uuid, text, text, text)
  from anon, authenticated, public;
grant execute on function public.grant_marketing_consent(uuid, text, text, text)
  to service_role;
