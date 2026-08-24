-- Realtime Authorization for the per-user notification push channel.
-- Topic: notify:user:<user_id>. Per-user, not per-role/tier: a shared
-- channel's membership itself is informative (anyone subscribed to
-- notify:role:admin can infer "a broadcast is happening" from channel
-- activity alone, correctly-scoped RLS notwithstanding) — a per-user channel
-- removes that inference surface entirely.
--
-- A client channel must be created with { config: { private: true } } to be
-- subject to this policy at all; a public channel skips authorization
-- entirely. See docs/notification-center-plan.md §2 for the SDK-upgrade
-- prerequisite (the currently pinned @supabase/realtime-js has no `private`
-- channel option at all).

create policy notify_own_channel_select on realtime.messages
for select to authenticated
using (
  (select realtime.topic()) = 'notify:user:' || (select auth.uid())::text
  and realtime.messages.extension = 'broadcast'
);

-- Deliberately no INSERT policy for `authenticated` — readers never publish.
-- Only the service-role key (used server-side by
-- notification_service.publish_realtime) posts to this endpoint, and the
-- service role bypasses RLS entirely.
comment on policy notify_own_channel_select on realtime.messages is
  'Notification Center: a reader may only subscribe to their own private '
  'broadcast topic. No corresponding INSERT policy — readers never publish.';
