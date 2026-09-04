-- profiles.tier becomes a foreign key into the catalogue seeded by the previous
-- migration. Second of two files deliberately: a seeded table is inert until
-- something references it, so the pair sequences cleanly and supabase/README.md
-- rule 1 (one concern per migration) needs no exception header.
-- See docs/reader-quota-plan.md §1.1.
--
-- ROW COUNTS BEFORE (verified through the MCP the same day, per README's
-- "Checking that a migration touched no rows"): public.profiles holds 4 rows,
-- all tier = 'free', none null. profiles.tier is NOT NULL with default 'free',
-- so the backfill below is expected to touch ZERO rows and therefore to fire
-- neither on_profile_update (which would bump updated_at on every profile) nor
-- the consent-record trigger. There is no `tier is null` clause: it would be
-- dead against a NOT NULL column.
--
-- VERIFIED AFTER: 4 profiles, 0 orphans, 4 distinct updated_at values unchanged.

-- Any value a live profile already carries becomes a tier of its own, so the
-- constraint cannot fail with 23503 on data that predates it. On this project
-- it inserts nothing; it exists so the migration is correct on any database.
insert into public.tiers (key, label_en, label_ar, daily_message_limit, ordering)
select distinct p.tier, initcap(p.tier), p.tier, 200, 100
  from public.profiles p
 where p.tier not in (select key from public.tiers)
   and p.tier ~ '^[a-z][a-z0-9_]{0,31}$';

-- Anything left that still does not match a tier key (a value the regex above
-- refuses, so it could never have been a valid key) falls back to the structural
-- default rather than blocking the constraint.
update public.profiles set tier = 'free'
 where tier not in (select key from public.tiers);

alter table public.profiles
  add constraint profiles_tier_fkey foreign key (tier)
  references public.tiers(key) on update cascade on delete restrict;

-- supabase/README.md rule 4: every foreign key gets an index in the migration
-- that creates it. Without it, `admin_delete_tier` and any ON UPDATE CASCADE
-- would sequentially scan profiles while holding a lock.
create index profiles_tier_idx on public.profiles (tier);

-- Fail the whole migration rather than apply half of it if anything is orphaned.
do $$
declare
  v_orphans integer;
begin
  select count(*) into v_orphans
    from public.profiles p
   where p.tier not in (select key from public.tiers);
  if v_orphans > 0 then
    raise exception 'profiles.tier has % rows with no matching tier; refusing', v_orphans;
  end if;
end $$;
