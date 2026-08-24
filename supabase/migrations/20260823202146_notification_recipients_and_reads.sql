-- Recipient snapshots and per-reader read/dismiss/acknowledge tracking.
-- Second concern of the notification schema (supabase/README.md rule 1).

create table if not exists public.notification_recipients (
  -- Surrogate key: user_id must stay nullable for ON DELETE SET NULL, which a
  -- composite (notification_id, user_id) primary key would rule out —
  -- Postgres makes every PK column implicitly NOT NULL, so that shape would
  -- make account deletion FAIL instead of anonymize.
  id               bigint generated always as identity primary key,
  notification_id  uuid not null references public.notifications(id),
  -- Real FK, ON DELETE SET NULL: this is reader-subject data, not actor
  -- attribution (contrast public.audit_log.actor_id and
  -- notifications.target_user_id, both deliberately un-anonymized).
  -- Anonymizing on deletion while keeping the row preserves aggregate
  -- audience-size counts without keeping a deleted reader's identity
  -- attached to them.
  user_id          uuid references auth.users(id) on delete set null,
  created_at       timestamptz not null default now(),
  unique (notification_id, user_id)
);

-- No separate index on notification_id alone: the unique constraint above
-- already leads with it, so a dedicated index would be redundant.
create index if not exists notification_recipients_user_idx
  on public.notification_recipients (user_id, notification_id);

alter table public.notification_recipients enable row level security;
revoke all on public.notification_recipients from anon, authenticated;

comment on table public.notification_recipients is
  'Snapshot of targeted recipients for role/tier/user-targeted notifications, '
  'taken at send time (excludes disabled accounts). Not populated for '
  'target_kind=all, whose delivery stays dynamic. Service-role only.';

create table if not exists public.user_notification_reads (
  id               bigint generated always as identity primary key,  -- same surrogate-key fix as above
  notification_id  uuid not null references public.notifications(id),
  user_id          uuid references auth.users(id) on delete set null,  -- same anonymize-on-delete reasoning
  served_at        timestamptz,   -- stamped when a REST response for /active or /history included this row —
                                  -- a network fact, not a claim about client-side rendering
  read_at          timestamptz,   -- inbox item opened
  dismissed_at     timestamptz,   -- toast/banner dismissed (never set for a modal — see acknowledged_at)
  acknowledged_at  timestamptz,   -- modal's explicit Acknowledge action only — never implied by Escape/
                                  -- backdrop-click, and never set for a toast/banner (type-checked by the RPC)
  created_at       timestamptz not null default now(),
  unique (notification_id, user_id)
);

create index if not exists user_notification_reads_user_idx
  on public.user_notification_reads (user_id, created_at desc);
create index if not exists user_notification_reads_notification_idx
  on public.user_notification_reads (notification_id);

alter table public.user_notification_reads enable row level security;
revoke all on public.user_notification_reads from anon, authenticated;

comment on table public.user_notification_reads is
  'Per-reader served/read/dismissed/acknowledged timestamps. Vocabulary used '
  'throughout: targeted -> served -> read -> dismissed -> acknowledged. '
  '"Delivered" is avoided as a claim this app cannot verify. Service-role only.';
