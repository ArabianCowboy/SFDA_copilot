-- Bound the reader-writable text/jsonb columns on public.profiles.
--
-- WHY
-- ---
-- `profiles` carries exactly one CHECK — profiles_role_chk
-- (20260814005509_lock_profile_privileges_and_repair_signup.sql:104-113).
-- `organization`, `specialization` are unbounded text and `preferences` is
-- unbounded jsonb; the browser inputs carry no maxlength (index.html:283-297,
-- verified live 2026-08-23: profiles has 4 rows, longest organization/
-- specialization values are well under 200 chars, preferences is the single
-- key '{"theme":"system"}'). A reader can otherwise store megabytes, and
-- admin_update_profile copies the before/after rows into audit_log
-- (20260814200342_admin_update_profile.sql:97-106), so an unbounded value
-- there is copied twice.
--
-- full_name is deliberately NOT bounded here. It becomes a stored generated
-- column in the identity-cutover migration that follows this one, and a
-- generated column cannot be written — the only value it can ever hold is the
-- concatenation of first_name and family_name, which are bounded on their own
-- terms. See docs/profile-refactor-plan.md §16·1 for why a combined-length
-- check on the generated column would reject valid data instead.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction (20260814005509…sql:35-43).

alter table public.profiles
  add constraint profiles_organization_len_chk
    check (organization is null or char_length(organization) <= 200),
  add constraint profiles_specialization_len_chk
    check (specialization is null or char_length(specialization) <= 200),
  add constraint profiles_preferences_size_chk
    check (preferences is null or octet_length(preferences::text) <= 4096);
