-- Store the reader's current marketing-consent record on public.profiles.
-- docs/profile-refactor-plan.md Step 6 / Spec 3.
--
-- WHY NOT public.audit_log
-- ------------------------
-- audit_log records administrative actions and deliberately survives account
-- deletion (20260814032139_audit_log.sql). Consent is subject-owned profile
-- data, must be readable by the subject, and should leave with the profile
-- when auth.users cascades it (profiles.id -> auth.users ON DELETE CASCADE).
--
-- WHY FOUR TIMESTAMPS/CONTEXT FIELDS, NOT ONE marketing_consent_at
-- ------------------------------------------------------------------
-- A single timestamp restamped on every flip records "last changed", not
-- "consent was granted" -- it loses the grant time on withdrawal. This
-- records current state, latest grant time, latest withdrawal time, and the
-- policy version/language/surface the current-or-latest grant was made
-- under. If a future legal requirement becomes "retain every grant/
-- withdrawal cycle", these columns are insufficient and an event table
-- should replace them -- this is NOT immutable history, only current state.
--
-- No explicit BEGIN/COMMIT: the migration runner owns the transaction.

-- ---------------------------------------------------------------------------
-- 1. Consent record columns.
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column marketing_consent boolean not null default false,
  add column marketing_consent_granted_at timestamptz,
  add column marketing_consent_withdrawn_at timestamptz,
  add column marketing_consent_policy_version text,
  add column marketing_consent_language text,
  add column marketing_consent_surface text,
  add column marketing_consent_granted_while_unconfirmed boolean;

-- Every constraint is conditional on the GRANTED state. Withdrawal changes the
-- state to false first, so malformed legacy context can never prevent it.
-- Intentionally no CHECK coupling age to marketing_consent: withdrawal offers
-- to clear age but does not require it.
alter table public.profiles
  add constraint profiles_marketing_consent_grant_chk
    check (
      not marketing_consent
      or (
        marketing_consent_granted_at is not null
        and marketing_consent_policy_version is not null
        and marketing_consent_policy_version =
              btrim(marketing_consent_policy_version)
        and char_length(marketing_consent_policy_version) between 1 and 64
        and marketing_consent_language in ('en', 'ar')
        and marketing_consent_surface is not null
        and marketing_consent_surface = btrim(marketing_consent_surface)
        and char_length(marketing_consent_surface) between 1 and 32
        and marketing_consent_granted_while_unconfirmed is not null
      )
    );

-- ---------------------------------------------------------------------------
-- 2. Server-owned timestamps and grant context.
-- ---------------------------------------------------------------------------
create or replace function public.profiles_set_marketing_consent_record()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_unconfirmed boolean;
begin
  new.marketing_consent := coalesce(new.marketing_consent, false);

  if tg_op = 'INSERT' then
    if new.marketing_consent then
      if new.marketing_consent_policy_version is null
         or new.marketing_consent_policy_version
              is distinct from btrim(new.marketing_consent_policy_version)
         or char_length(new.marketing_consent_policy_version)
              not between 1 and 64
         or new.marketing_consent_language not in ('en', 'ar')
         or new.marketing_consent_surface is null
         or new.marketing_consent_surface
              is distinct from btrim(new.marketing_consent_surface)
         or char_length(new.marketing_consent_surface)
              not between 1 and 32 then
        raise exception 'marketing consent requires valid policy, language and surface'
          using errcode = '22023';
      end if;

      select (u.email_confirmed_at is null)
        into v_unconfirmed
        from auth.users u
       where u.id = new.id;

      new.marketing_consent_granted_at := statement_timestamp();
      new.marketing_consent_withdrawn_at := null;
      new.marketing_consent_granted_while_unconfirmed :=
        coalesce(v_unconfirmed, true);
    else
      -- An unticked signup is an absence of grant, not a withdrawal event.
      new.marketing_consent_granted_at := null;
      new.marketing_consent_withdrawn_at := null;
      new.marketing_consent_policy_version := null;
      new.marketing_consent_language := null;
      new.marketing_consent_surface := null;
      new.marketing_consent_granted_while_unconfirmed := null;
    end if;

    return new;
  end if;

  if new.marketing_consent is not distinct from old.marketing_consent then
    -- A no-op cannot restamp time or rewrite the disclosure under which an
    -- existing grant was captured.
    new.marketing_consent_granted_at :=
      old.marketing_consent_granted_at;
    new.marketing_consent_withdrawn_at :=
      old.marketing_consent_withdrawn_at;
    new.marketing_consent_policy_version :=
      old.marketing_consent_policy_version;
    new.marketing_consent_language :=
      old.marketing_consent_language;
    new.marketing_consent_surface :=
      old.marketing_consent_surface;
    new.marketing_consent_granted_while_unconfirmed :=
      old.marketing_consent_granted_while_unconfirmed;

  elsif new.marketing_consent then
    -- This is a grant or re-grant. The previous withdrawal time remains
    -- visible; state=true disambiguates it from the current grant.
    if new.marketing_consent_policy_version is null
       or new.marketing_consent_policy_version
            is distinct from btrim(new.marketing_consent_policy_version)
       or char_length(new.marketing_consent_policy_version)
            not between 1 and 64
       or new.marketing_consent_language not in ('en', 'ar')
       or new.marketing_consent_surface is null
       or new.marketing_consent_surface
            is distinct from btrim(new.marketing_consent_surface)
       or char_length(new.marketing_consent_surface)
            not between 1 and 32 then
      raise exception 'marketing consent requires valid policy, language and surface'
        using errcode = '22023';
    end if;

    select (u.email_confirmed_at is null)
      into v_unconfirmed
      from auth.users u
     where u.id = new.id;

    new.marketing_consent_granted_at := statement_timestamp();
    new.marketing_consent_withdrawn_at :=
      old.marketing_consent_withdrawn_at;
    new.marketing_consent_granted_while_unconfirmed :=
      coalesce(v_unconfirmed, true);

  else
    -- Withdrawal never validates or clears age and never examines grant
    -- context. It therefore cannot be blocked by stale context or by
    -- declining the offer to erase age.
    new.marketing_consent_granted_at :=
      old.marketing_consent_granted_at;
    new.marketing_consent_withdrawn_at := statement_timestamp();
    new.marketing_consent_policy_version :=
      old.marketing_consent_policy_version;
    new.marketing_consent_language :=
      old.marketing_consent_language;
    new.marketing_consent_surface :=
      old.marketing_consent_surface;
    new.marketing_consent_granted_while_unconfirmed :=
      old.marketing_consent_granted_while_unconfirmed;
  end if;

  return new;
end;
$$;

revoke execute on function public.profiles_set_marketing_consent_record()
  from anon, authenticated, public;

drop trigger if exists profiles_set_marketing_consent_record
  on public.profiles;

create trigger profiles_set_marketing_consent_record
  before insert or update on public.profiles
  for each row
  execute function public.profiles_set_marketing_consent_record();

-- ---------------------------------------------------------------------------
-- 3. Extend the existing privilege guard to cover the three server-owned
--    consent fields, in BOTH its INSERT and UPDATE branches -- this
--    replaces 20260822224942_profile_privilege_guard_covers_insert.sql's
--    definition, not Spec 3's own text verbatim (that text predates this
--    project's live INSERT-branch fix).
-- ---------------------------------------------------------------------------
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
      or new.last_seen_at     is not null
      or new.marketing_consent_granted_at is not null
      or new.marketing_consent_withdrawn_at is not null
      or new.marketing_consent_granted_while_unconfirmed is not null
    ) then
      raise exception
        'profiles.role, tier, is_disabled, disabled_at, disabled_by, '
        'disabled_reason, last_seen_at and consent timestamps are '
        'server-owned'
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
    or new.last_seen_at     is distinct from old.last_seen_at
    or new.marketing_consent_granted_at
         is distinct from old.marketing_consent_granted_at
    or new.marketing_consent_withdrawn_at
         is distinct from old.marketing_consent_withdrawn_at
    or new.marketing_consent_granted_while_unconfirmed
         is distinct from old.marketing_consent_granted_while_unconfirmed
  ) then
    raise exception
      'profiles.role, tier, is_disabled, disabled_at, disabled_by, '
      'disabled_reason, last_seen_at and consent timestamps are '
      'server-owned'
      using errcode = '42501';
  end if;
  return new;
end;
$$;

revoke execute on function public.profiles_guard_privilege_columns()
  from anon, authenticated, public;

-- BEFORE ROW triggers of the same kind fire by trigger name. On UPDATE:
--
--   on_profile_update
--   profiles_guard_privilege_columns
--   profiles_set_marketing_consent_record
--
-- The guard therefore rejects a caller-supplied timestamp before the setter
-- runs -- both already exist as triggers on this table (no drop/recreate
-- needed here, only the function body changed above).

-- ---------------------------------------------------------------------------
-- 4. Column grants. State and grant context are reader-supplied. The
--    timestamps and the pre-confirmation fact are never granted, so they
--    cannot appear in a PostgREST write payload at all -- the explicit
--    revoke below is documentation, not a functional change (nothing has
--    ever granted these columns).
-- ---------------------------------------------------------------------------
grant insert (
  marketing_consent,
  marketing_consent_policy_version,
  marketing_consent_language,
  marketing_consent_surface
) on public.profiles to authenticated;

grant update (
  marketing_consent,
  marketing_consent_policy_version,
  marketing_consent_language,
  marketing_consent_surface
) on public.profiles to authenticated;

revoke insert (
  marketing_consent_granted_at,
  marketing_consent_withdrawn_at,
  marketing_consent_granted_while_unconfirmed
), update (
  marketing_consent_granted_at,
  marketing_consent_withdrawn_at,
  marketing_consent_granted_while_unconfirmed
) on public.profiles from authenticated, anon;

-- ---------------------------------------------------------------------------
-- 5. Signup capture: handle_new_user now reads consent fields out of GoTrue
--    metadata too, in the same coerce-never-raise style Step 4's version
--    already established for first_name/family_name/age. A malformed or
--    missing consent value degrades to "no consent", never to a raised
--    exception -- see 20260822225415_profile_identity_atomic_cutover.sql's
--    own comment for why an AFTER INSERT trigger raising here would roll
--    back auth.users creation itself.
-- ---------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_meta           jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
  v_age_text       text;
  v_age            integer;
  v_first_name     text;
  v_family_name    text;
  v_consent        boolean := false;
  v_policy_version text;
  v_language       text;
begin
  v_first_name :=
    nullif(left(btrim(v_meta ->> 'first_name'), 100), '');
  v_family_name :=
    nullif(left(btrim(v_meta ->> 'family_name'), 100), '');

  v_age_text := v_meta ->> 'age';
  if pg_catalog.pg_input_is_valid(v_age_text, 'integer') then
    v_age := v_age_text::integer;
  end if;

  if v_age is not null and v_age not between 13 and 120 then
    v_age := null;
  end if;

  if jsonb_typeof(v_meta -> 'marketing_consent') = 'boolean' then
    v_consent := (v_meta ->> 'marketing_consent')::boolean;
  end if;

  v_policy_version :=
    nullif(left(btrim(v_meta ->> 'marketing_consent_policy_version'), 64), '');

  v_language :=
    case v_meta ->> 'marketing_consent_language'
      when 'en' then 'en'
      when 'ar' then 'ar'
      else null
    end;

  -- A boolean without the disclosure version and language is not an
  -- adequate consent record. Coerce it to a decline rather than aborting
  -- signup.
  if v_consent
     and (v_policy_version is null or v_language is null) then
    v_consent := false;
  end if;

  -- The signup UI gates age behind consent. A direct GoTrue caller cannot
  -- bypass that collection rule by submitting age with consent=false.
  if not v_consent then
    v_age := null;
  end if;

  insert into public.profiles (
    id, first_name, family_name, age, role,
    organization, specialization, preferences,
    marketing_consent,
    marketing_consent_policy_version,
    marketing_consent_language,
    marketing_consent_surface
  )
  values (
    new.id, v_first_name, v_family_name, v_age, 'user',
    '', '', '{"theme": "system"}'::jsonb,
    v_consent,
    case when v_consent then v_policy_version end,
    case when v_consent then v_language end,
    case when v_consent then 'signup' end
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

revoke execute on function public.handle_new_user()
  from anon, authenticated, public;
