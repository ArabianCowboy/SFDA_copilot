-- app_settings.updated_at is maintained by the database, not by the caller.
--
-- The direct upsert path sent `updated_at: "now()"` as a JSON string. Postgres
-- accepts that as a timestamp literal — verified against this project, the row
-- updates with the correct time — but depending on that parse is fragile, and
-- it also let a caller write any timestamp it liked into a field whose whole
-- job is to say when the row actually changed.
--
-- Same shape as handle_profile_update on public.profiles, so the two tables
-- keep their updated_at the same way.

create or replace function public.app_settings_touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists app_settings_set_updated_at on public.app_settings;
create trigger app_settings_set_updated_at
  before insert or update on public.app_settings
  for each row execute function public.app_settings_touch_updated_at();

revoke execute on function public.app_settings_touch_updated_at()
  from anon, authenticated, public;
