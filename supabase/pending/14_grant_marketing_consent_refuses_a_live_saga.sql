-- Marketing consent may not be GRANTED by an account with a live deletion saga.
--
-- WHY THIS IS A SEPARATE FILE AND NOT PART OF 02
-- ----------------------------------------------
-- `public.account_deletion_is_live(uuid)` does not exist until 08, and 08
-- cannot move earlier: it depends on the ledger table in 07, which depends on
-- the destructive FK change in 06. So 02 ships the function without this gate
-- and this file adds it once the predicate exists. Applying 02 without 14 is
-- safe only for as long as no saga row can exist, which is true until 07.
--
-- THE HOLE THIS CLOSES
-- --------------------
-- 02 deliberately carries no active-account check, on the stated grounds that
-- "the refusal comes from the route's `_gate`, not from a second check here".
-- That reasoning is sound for a DISABLED account and wrong for a PENDING one:
-- `_gate` runs `_authenticate_request`, which refuses only `is_disabled`
-- (`web/api/app.py:932-933`), and a deletion-pending account is deliberately
-- never disabled — that is what keeps its cancel path reachable. So a reader
-- inside the 30-day grace window reached `grant_marketing_consent` and could
-- opt INTO marketing while the rest of their profile was frozen.
--
-- Two things were wrong with that, not one:
--   * it inverted D5's own ordering — a disabled account cannot grant, yet a
--     pending-deletion account, which is strictly further along toward
--     erasure, could. Collecting a fresh marketing permission from someone who
--     has asked to be erased is the last thing this schema should allow.
--     (Slice 2c kept this refusal while unfreezing everything else in grace:
--     a pending account is fully usable — chat, profile, preferences — and
--     the grant direction stays closed anyway. The reader-facing copy names
--     the carve-out rather than promising "everything".)
--
-- WITHDRAWAL IS UNAFFECTED, AND THAT IS THE POINT.
-- `update_own_marketing_consent` (01) stays ungated: a pending or disabled
-- reader must always be able to withdraw. Only the grant direction closes.
--
-- Contract: unchanged from 02 — `service_role` only, `p_owner_id` first and
-- filtered on inside, `security definer`, `search_path = ''`. This file only
-- adds a refusal; the signature, the column list and the grants are identical.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: lives in supabase/pending/ (see supabase/README.md). Apply with
-- apply_migration, read the real version back from list_migrations, then
-- `git mv` it into supabase/migrations/ under that name. MUST land after 08.

create or replace function public.grant_marketing_consent(
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

  -- NEW IN THIS MIGRATION, and the only change to 02's body. Checked before
  -- the payload validation so a pending account gets the same refusal whatever
  -- it sends.
  if public.account_deletion_is_live(p_owner_id) then
    raise exception 'DL007: marketing consent cannot be granted while a deletion is live'
      using errcode = 'DL007';
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
