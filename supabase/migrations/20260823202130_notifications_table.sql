-- Admin Broadcast & Reader Notification Center: notifications table.
-- One concern: the notification record itself. Recipient/read tracking are
-- separate migrations (supabase/README.md rule 1).
--
-- Zero-policy RLS, the audit_log template (supabase/README.md, and this
-- table's own header reasoning): every reader-facing path in TODO.md's own
-- spec is a Flask route (GET /active, GET /history, POST /mark-read), never
-- a direct-from-browser Supabase call, so there is no browser-direct access
-- path here to gate with a policy.

create table if not exists public.notifications (
  id             uuid primary key default gen_random_uuid(),

  type           text not null check (type in ('toast','banner','modal')),
  severity       text not null default 'info' check (severity in ('info','success','warning','danger')),

  title_en       text not null check (char_length(title_en) between 1 and 200),
  title_ar       text not null check (char_length(title_ar) between 1 and 200),
  body_en        text not null check (char_length(body_en) between 1 and 2000),
  body_ar        text not null check (char_length(body_ar) between 1 and 2000),

  target_kind    text not null check (target_kind in ('all','role','tier','user')),
  target_role    text check (target_role is null or target_role in ('user','admin')),
  target_tier    text,
  -- Not anonymized on account deletion — deliberately. This column records an
  -- administrative instruction ("who the operator chose"), the same category
  -- as audit_log's intentionally-retained before/after values, not reader-
  -- subject data. Contrast notification_recipients.user_id and
  -- user_notification_reads.user_id (next migration), which ARE anonymized
  -- because they record what a reader did, not what an admin decided.
  target_user_id uuid,
  check (
    (target_kind = 'all'  and target_role is null and target_tier is null and target_user_id is null) or
    (target_kind = 'role' and target_role is not null and target_tier is null and target_user_id is null) or
    (target_kind = 'tier' and target_tier is not null and target_role is null and target_user_id is null) or
    (target_kind = 'user' and target_user_id is not null and target_role is null and target_tier is null)
  ),

  -- Metrics denominator, captured at send time for EVERY target_kind
  -- including 'all' (a plain count, not a full recipient snapshot for
  -- 'all'). Answers "% who read this" as a stable historical fact even
  -- though 'all' delivery itself stays dynamic (see admin_create_notification).
  target_count   integer not null check (target_count >= 0),

  requires_ack   boolean not null default false,
  check (type <> 'modal' or requires_ack = true),
  check (type = 'modal' or requires_ack = false),

  -- Denormalised actor, no FK — same reasoning as audit_log.actor_id: an
  -- operator account later deleted must not erase who sent this.
  created_by       uuid not null,
  created_by_email text not null,

  -- Idempotency: scoped to the actor, not global, so a colliding id from a
  -- different admin can't silently return someone else's row. Paired with a
  -- payload hash so a same-id-different-content replay is a conflict, not a
  -- silent stale success.
  client_request_id uuid not null,
  request_payload_hash text not null,
  unique (created_by, client_request_id),

  -- Provenance for a resend, not a live relationship — purely for the
  -- history table's "resent from #..." display and audit trail.
  resend_of         uuid references public.notifications(id),

  created_at     timestamptz not null default now(),
  expires_at     timestamptz,
  deactivated_at timestamptz,
  deactivated_by uuid,
  deleted_at     timestamptz,
  deleted_by     uuid,

  check (expires_at is null or expires_at > created_at)
);

create index if not exists notifications_active_idx
  on public.notifications (target_kind, created_at desc)
  where deactivated_at is null and deleted_at is null;
create index if not exists notifications_created_by_idx on public.notifications (created_by);
create index if not exists notifications_target_user_idx on public.notifications (target_user_id)
  where target_kind = 'user';
create index if not exists notifications_resend_of_idx on public.notifications (resend_of);

alter table public.notifications enable row level security;
revoke all on public.notifications from anon, authenticated;

comment on table public.notifications is
  'Admin-authored broadcast notifications (toast/banner/modal). Service-role '
  'only; every reader/admin path is a Flask route through security definer '
  'RPCs, never direct browser access. RLS enabled with no policies by design.';
