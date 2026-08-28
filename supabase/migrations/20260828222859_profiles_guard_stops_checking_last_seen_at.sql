-- profiles.last_seen_at has been dead since 20260828135721_profile_last_seen_table.sql
-- moved presence tracking to public.profile_last_seen: nothing writes the column any
-- more (touch_last_seen(uuid) writes profile_last_seen; admin_get_user reads it via a
-- left join, not from profiles). This is step 1 of dropping it (TODO.md "Drop
-- profiles.last_seen_at, the column this feature replaced"): the guard trigger below
-- is the only other thing in the schema that still references the column, so it has to
-- stop before the column can go -- a DROP COLUMN with this trigger left as-is would abort
-- on the next INSERT/UPDATE with a 42703 (column does not exist). The destructive drop
-- itself is a separate migration per supabase/README.md rule 2.
--
-- CREATE OR REPLACE, not DROP + CREATE: same name, same signature, same triggers already
-- pointed at it (profiles_guard_privilege_columns fires by name, no re-attach needed).
-- Body otherwise copied verbatim from 20260823014034_marketing_consent_record.sql with
-- the last_seen_at clause and its error-message mention removed from both branches.
create or replace function public.profiles_guard_privilege_columns()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if current_user in ('authenticated', 'anon') and (
         new.role            <> 'user'
      or new.tier             <> 'free'
      or new.is_disabled
      or new.disabled_at      is not null
      or new.disabled_by      is not null
      or new.disabled_reason  is not null
      or new.marketing_consent_granted_at is not null
      or new.marketing_consent_withdrawn_at is not null
      or new.marketing_consent_granted_while_unconfirmed is not null
    ) then
      raise exception
        'profiles.role, tier, is_disabled, disabled_at, disabled_by, '
        'disabled_reason and consent timestamps are server-owned'
        using errcode = '42501';
    end if;
    return new;
  end if;

  if current_user in ('authenticated', 'anon') and (
       new.role            is distinct from old.role
    or new.tier             is distinct from old.tier
    or new.is_disabled      is distinct from old.is_disabled
    or new.disabled_at      is distinct from old.disabled_at
    or new.disabled_by      is distinct from old.disabled_by
    or new.disabled_reason  is distinct from old.disabled_reason
    or new.marketing_consent_granted_at
         is distinct from old.marketing_consent_granted_at
    or new.marketing_consent_withdrawn_at
         is distinct from old.marketing_consent_withdrawn_at
    or new.marketing_consent_granted_while_unconfirmed
         is distinct from old.marketing_consent_granted_while_unconfirmed
  ) then
    raise exception
      'profiles.role, tier, is_disabled, disabled_at, disabled_by, '
      'disabled_reason and consent timestamps are server-owned'
      using errcode = '42501';
  end if;
  return new;
end;
$$;

revoke execute on function public.profiles_guard_privilege_columns()
  from anon, authenticated, public;
