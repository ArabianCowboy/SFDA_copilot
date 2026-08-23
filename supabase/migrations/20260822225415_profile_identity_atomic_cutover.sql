-- Replace public.profiles.full_name with a stored generated display name and
-- move every database writer and privilege in the same atomic cutover.
--
-- WHY THIS CANNOT BE SPLIT
-- ------------------------
-- public.handle_new_user writes full_name
-- (20260814005509_lock_profile_privileges_and_repair_signup.sql:58-67),
-- public.admin_update_profile writes it
-- (20260814200342_admin_update_profile.sql:76-80), and the shipped browser
-- includes it in an upsert payload (static/js/modules/handlers.js:1514-1521).
-- A generated column rejects all three writes. Sequencing the column
-- conversion before the writers are updated breaks signup and both save
-- paths for the length of the deployment.
--
-- DESTRUCTIVE-CHECK RECORD, 2026-08-23
-- ------------------------------------
-- Verified live immediately before writing this migration:
--   * public.profiles has 4 rows and auth.users has 4 rows; 0 lack a profile.
--   * 3 full_name values are non-null; the maximum length is 22.
--   * 2 of the 3 names begin with "Dr.", one has three tokens ("Mohammed Exam
--     Tomorrow") -- so a mechanical token split (e.g. split_part on the first
--     space) would file "Dr." as a given name for two of three readers. That
--     approach, originally proposed in this plan's section 6.5, is withdrawn
--     -- see docs/profile-refactor-plan.md section 15.2.
--   * profiles_full_name_len_chk and every other name-length check are
--     absent (profile_column_bounds, applied earlier today, deliberately did
--     not add one -- see its own header).
--   * The only profile triggers are on_profile_update (sets updated_at only)
--     and profiles_guard_privilege_columns (administered columns only,
--     just extended to BEFORE INSERT OR UPDATE by
--     profile_privilege_guard_covers_insert, applied earlier today) --
--     neither references full_name/first_name/family_name/age.
--   * No index on public.profiles mentions full_name (only profiles_pkey and
--     profiles_disabled_by_idx exist).
--   * The exact 4 rows (id, full_name, organization, specialization) were
--     read and recorded before this migration ran; see
--     docs/profile-refactor-plan.md section 15.2 for the full_name values.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction. This follows the warning at
-- 20260814005509_lock_profile_privileges_and_repair_signup.sql:35-43.

-- ---------------------------------------------------------------------------
-- 1. Add the writable identity components.
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column first_name  text,
  add column family_name text,
  add column age         smallint;

-- Preserve legacy display names verbatim rather than pretending that titles
-- and multi-token names can be decomposed mechanically. The generated value
-- stays byte-for-byte equal; family_name stays explicitly unknown (null),
-- not empty -- nobody but the three named readers knows whether "Dr." is
-- part of a given name. They correct it themselves on /account.
update public.profiles
   set first_name = full_name,
       family_name = null
 where full_name is not null;

-- Names are normalised at the storage boundary. NULL means unknown; an empty
-- or whitespace-only string does not become a second spelling of unknown.
alter table public.profiles
  add constraint profiles_first_name_chk
    check (
      first_name is null
      or (
        first_name = btrim(first_name)
        and char_length(first_name) between 1 and 100
      )
    ),
  add constraint profiles_family_name_chk
    check (
      family_name is null
      or (
        family_name = btrim(family_name)
        and char_length(family_name) between 1 and 100
      )
    ),
  add constraint profiles_age_chk
    check (age is null or age between 13 and 120);

-- Abort before the destructive statement if the conservative backfill failed
-- to preserve even one legacy display value.
do $$
begin
  if exists (
    select 1
      from public.profiles p
     where p.full_name is distinct from
       case
         when p.first_name is null and p.family_name is null then null::text
         when p.first_name is null then p.family_name
         when p.family_name is null then p.first_name
         else p.first_name || ' ' || p.family_name
       end
  ) then
    raise exception 'identity backfill does not preserve every full_name';
  end if;
end
$$;

-- ---------------------------------------------------------------------------
-- 2. Signup writer: stop naming full_name before it becomes generated, and
--    harden against client-supplied signup metadata (Spec 2 / section 16.2).
-- ---------------------------------------------------------------------------
-- pg_input_is_valid() rejects malformed and out-of-range integer input before
-- a cast is ever attempted. A bad metadata value degrades to NULL rather than
-- raising -- which would roll back auth.users creation itself, the failure
-- this migration's predecessor already warns about
-- (20260814005509_lock_profile_privileges_and_repair_signup.sql:48-50).
-- Consent fields are NOT read here: those columns do not exist until Step 6,
-- gated on the bilingual policy. This is the identity-only hardening pass;
-- Step 6 replaces this function again once consent columns land.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_meta        jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
  v_age_text    text;
  v_age         integer;
  v_first_name  text;
  v_family_name text;
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

  insert into public.profiles (
    id, first_name, family_name, age, role,
    organization, specialization, preferences
  )
  values (
    new.id, v_first_name, v_family_name, v_age, 'user',
    '', '', '{"theme": "system"}'::jsonb
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

revoke execute on function public.handle_new_user()
  from anon, authenticated, public;

-- ---------------------------------------------------------------------------
-- 3. Administrative writer: replace the old signature, not overload it.
-- ---------------------------------------------------------------------------
-- CREATE OR REPLACE with different arguments would leave the old RPC
-- callable. Dropping that overload ensures no service path still accepts
-- p_full_name.
drop function public.admin_update_profile(
  uuid, text, text, text, timestamptz, uuid, text, text, text
);

create function public.admin_update_profile(
  p_user_id             uuid,
  p_first_name          text,
  p_family_name         text,
  p_age                 smallint,
  p_organization        text,
  p_specialization      text,
  p_expected_updated_at timestamptz,
  p_actor_id            uuid,
  p_actor_email         text,
  p_request_ip          text,
  p_user_agent          text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_before     jsonb;
  v_after      jsonb;
  v_actor_ok   boolean;
  v_updated_at timestamptz;
begin
  select (pr.role = 'admin' and pr.is_disabled = false)
    into v_actor_ok
    from public.profiles pr
   where pr.id = p_actor_id;

  if p_actor_id is not null and coalesce(v_actor_ok, false) = false then
    raise exception 'actor is no longer an administrator'
      using errcode = 'AD004';
  end if;

  select to_jsonb(t), t.updated_at
    into v_before, v_updated_at
    from (
      select p.first_name, p.family_name, p.full_name, p.age,
             p.organization, p.specialization, p.updated_at
        from public.profiles p
       where p.id = p_user_id
       for update
    ) t;

  if v_before is null then
    raise exception 'no such account' using errcode = 'AD003';
  end if;

  if p_expected_updated_at is not null
     and v_updated_at is distinct from p_expected_updated_at then
    raise exception 'profile changed since it was loaded'
      using errcode = 'AD005';
  end if;

  update public.profiles
     set first_name     = p_first_name,
         family_name    = p_family_name,
         age            = p_age,
         organization   = p_organization,
         specialization = p_specialization
   where id = p_user_id;

  -- on_profile_update remains the sole owner of updated_at.
  select to_jsonb(t)
    into v_after
    from (
      select p.first_name, p.family_name, p.full_name, p.age,
             p.organization, p.specialization
        from public.profiles p
       where p.id = p_user_id
    ) t;

  if v_before - 'updated_at' = v_after then
    return v_after;
  end if;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, p_actor_email, 'user.profile_change',
    'user', p_user_id::text,
    v_before - 'updated_at', v_after,
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  return v_after;
end;
$$;

revoke execute on function public.admin_update_profile(
  uuid, text, text, smallint, text, text,
  timestamptz, uuid, text, text, text
) from anon, authenticated, public;

grant execute on function public.admin_update_profile(
  uuid, text, text, smallint, text, text,
  timestamptz, uuid, text, text, text
) to service_role;

-- ---------------------------------------------------------------------------
-- 4. Destructive conversion.
-- ---------------------------------------------------------------------------
-- No CASCADE. An unrecorded dependent object must abort the migration rather
-- than be silently dropped with the source column. profiles_full_name_len_chk
-- does not exist to drop (profile_column_bounds deliberately never added it
-- -- see docs/profile-refactor-plan.md section 16.1: a combined-length check
-- on a generated column can only reject data its own inputs already proved
-- valid).
alter table public.profiles
  drop column full_name,
  add column full_name text
    generated always as (
      case
        when first_name is null and family_name is null then null::text
        when first_name is null then family_name
        when family_name is null then first_name
        else first_name || ' ' || family_name
      end
    ) stored;

-- ---------------------------------------------------------------------------
-- 5. Column ACL cutover.
-- ---------------------------------------------------------------------------
-- Table-level grants would override every column decision, so withdraw them
-- first. The newly-generated column has no write grant; the explicit revoke
-- documents that this is intentional rather than an omission.
revoke insert, update on public.profiles from authenticated, anon;
revoke insert (full_name), update (full_name)
  on public.profiles from authenticated, anon;

grant insert (
  id, first_name, family_name, age,
  organization, specialization, preferences
) on public.profiles to authenticated;

-- id remains writable because PostgREST's upsert emits it in the conflict
-- update set, as documented at 20260814005509:144-149.
grant update (
  id, first_name, family_name, age,
  organization, specialization, preferences
) on public.profiles to authenticated;
