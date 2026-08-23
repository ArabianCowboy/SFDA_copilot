-- Audit log: who changed what, and when — recorded in the same transaction as
-- the change itself.
--
-- APPEND-ONLY IS ENFORCED BY PRIVILEGES, NOT RLS.
--
-- RLS is the wrong tool here and it is worth being explicit about why: the
-- service role BYPASSES row-level security, and the service role is the only
-- thing that ever writes this table. A policy would constrain exactly the roles
-- that already cannot reach it and none of the one that can.
--
-- So: REVOKE the ability to change history from the role that writes it, and a
-- trigger as the second lock. RLS stays enabled with zero policies so anon and
-- authenticated see nothing at all.
--
-- Honest limit, stated rather than overclaimed: the table OWNER can still drop
-- the trigger and re-grant. True append-only against a database superuser needs
-- log shipping off-box. For this threat model — an operator misusing the
-- console they were given — REVOKE plus trigger is the right stopping point.

create table if not exists public.audit_log (
  id           bigserial primary key,
  occurred_at  timestamptz not null default now(),

  -- Denormalised on purpose. actor_id references an account that may later be
  -- deleted, and an audit row that can no longer say who acted has lost the
  -- thing it exists to record. No FK, for the same reason.
  actor_id     uuid,
  actor_email  text,

  action       text not null,
  target_type  text,
  target_id    text,

  -- Only the keys that changed, not whole documents: a diff that includes
  -- everything makes the one field that moved impossible to see.
  before       jsonb,
  after        jsonb,

  request_ip   inet,
  user_agent   text,
  note         text
);

create index if not exists audit_log_time_idx   on public.audit_log (occurred_at desc);
create index if not exists audit_log_actor_idx  on public.audit_log (actor_id, occurred_at desc);
create index if not exists audit_log_target_idx on public.audit_log (target_type, target_id, occurred_at desc);

alter table public.audit_log enable row level security;

revoke all on public.audit_log from anon, authenticated;
revoke update, delete, truncate on public.audit_log from service_role;
grant insert, select on public.audit_log to service_role;
grant usage, select on sequence public.audit_log_id_seq to service_role;

create or replace function public.audit_log_is_append_only()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'public.audit_log is append-only';
end;
$$;

drop trigger if exists audit_log_no_rewrite on public.audit_log;
create trigger audit_log_no_rewrite
  before update or delete on public.audit_log
  for each row execute function public.audit_log_is_append_only();

comment on table public.audit_log is
  'Append-only record of administrative actions. Service-role insert/select only; '
  'UPDATE and DELETE are revoked and blocked by trigger. RLS enabled with no '
  'policies by design.';


-- ---------------------------------------------------------------------------
-- Settings write + audit row, in ONE transaction.
-- ---------------------------------------------------------------------------
-- Two separate statements can half-succeed, and the half that fails is always
-- the one you needed: a settings change with no record of who made it. A
-- function body is a single transaction, so either both rows land or neither
-- does — which is what makes "every change is recorded" a property of the
-- system rather than a promise about the application code.
--
-- Returns the committed settings document, so the caller reports what is
-- actually stored rather than what it hoped it stored.
create or replace function public.admin_write_settings(
  p_settings   jsonb,
  p_actor_id   uuid,
  p_actor_email text,
  p_before     jsonb,
  p_after      jsonb,
  p_request_ip text default null,
  p_user_agent text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_settings jsonb;
begin
  insert into public.app_settings (id, settings, updated_at, updated_by)
  values (1, p_settings, now(), p_actor_id)
  on conflict (id) do update
    set settings = excluded.settings,
        updated_at = now(),
        updated_by = excluded.updated_by
  returning settings into v_settings;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, p_actor_email, 'settings.update', 'settings', 'app_settings',
    p_before, p_after,
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  return v_settings;
end;
$$;

revoke execute on function public.admin_write_settings(jsonb, uuid, text, jsonb, jsonb, text, text)
  from anon, authenticated, public;
