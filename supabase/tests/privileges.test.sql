-- Table and column privileges, asserted in both directions.
-- ===========================================================================
-- The test that fails when a new table is born open, or when a revoke is
-- undone. Written against the post-hardening state, so it encodes the intended
-- grants rather than whatever the database happens to hold.
--
-- Run: paste into execute_sql. Reads the word after P0001 — PASS or FAIL.
-- See supabase/tests/README.md.

do $$
declare
  n int := 0;

  summary text;

  -- (role, table, privilege) triples that MUST be denied.
  denied text[][] := array[
    -- profiles: the identity and authorization table. TRUNCATE is the one that
    -- matters most — RLS does not cover it, so nothing else stops it.
    ['anon','profiles','SELECT'], ['anon','profiles','INSERT'],
    ['anon','profiles','UPDATE'], ['anon','profiles','DELETE'],
    ['anon','profiles','TRUNCATE'], ['anon','profiles','REFERENCES'],
    ['anon','profiles','TRIGGER'],
    ['authenticated','profiles','INSERT'], ['authenticated','profiles','UPDATE'],
    ['authenticated','profiles','DELETE'], ['authenticated','profiles','TRUNCATE'],
    ['authenticated','profiles','REFERENCES'], ['authenticated','profiles','TRIGGER'],
    -- service_role reads profiles and writes it only through the RPCs.
    ['service_role','profiles','INSERT'], ['service_role','profiles','UPDATE'],
    ['service_role','profiles','DELETE'], ['service_role','profiles','TRUNCATE'],

    -- No browser-direct WRITE path to any chat table. DELETE on chat_sessions is
    -- the one deliberate exception and is asserted as granted below.
    ['anon','chat_sessions','SELECT'], ['authenticated','chat_sessions','INSERT'],
    ['authenticated','chat_sessions','UPDATE'], ['authenticated','chat_sessions','TRUNCATE'],
    ['authenticated','chat_messages','DELETE'],
    ['authenticated','chat_message_sources','DELETE'],
    ['authenticated','chat_messages','INSERT'], ['authenticated','chat_messages','UPDATE'],
    ['authenticated','chat_messages','TRUNCATE'],
    ['authenticated','chat_message_sources','INSERT'],
    ['authenticated','chat_archive','SELECT'],
    -- service_role reads the chat tables; chat_append_turn writes them as its
    -- owner. 20260820131914 revoked these and this is what pins that.
    ['service_role','chat_sessions','INSERT'], ['service_role','chat_messages','INSERT'],
    ['service_role','chat_archive','INSERT'],

    -- audit_log is append-only by privilege, not only by trigger.
    ['service_role','audit_log','UPDATE'], ['service_role','audit_log','DELETE'],
    ['service_role','audit_log','TRUNCATE'],
    ['anon','audit_log','SELECT'], ['authenticated','audit_log','SELECT'],

    -- The five tables service_role lost its direct write surface on.
    ['service_role','app_settings','INSERT'], ['service_role','app_settings','UPDATE'],
    ['service_role','app_settings','TRUNCATE'],
    ['service_role','notifications','INSERT'], ['service_role','notifications','UPDATE'],
    ['service_role','notifications','DELETE'], ['service_role','notifications','SELECT'],
    ['service_role','notification_recipients','INSERT'],
    ['service_role','notification_recipients','DELETE'],
    ['service_role','user_notification_reads','INSERT'],
    ['service_role','user_notification_reads','UPDATE'],
    ['service_role','user_notification_reads','SELECT'],
    ['anon','notifications','SELECT'], ['authenticated','notifications','SELECT'],
    ['authenticated','user_notification_reads','SELECT'],

    -- The dead table, still present pending the drop-or-use decision.
    ['anon','chatbot_settings','SELECT'], ['anon','chatbot_settings','INSERT'],
    ['anon','chatbot_settings','TRUNCATE'],
    ['authenticated','chatbot_settings','SELECT'], ['authenticated','chatbot_settings','UPDATE'],

    -- profile_last_seen: no role holds anything on it, service_role included —
    -- every access path is touch_last_seen/admin_get_user, both security
    -- definer running as the table owner. See docs/data-policy-decisions.md's §4.
    -- The full seven-privilege set per role, not a subset: the migration does
    -- `revoke all`, and a test asserting only SELECT/INSERT/UPDATE/DELETE would
    -- pass against an accidental `grant truncate` or `grant references`.
    ['anon','profile_last_seen','SELECT'], ['anon','profile_last_seen','INSERT'],
    ['anon','profile_last_seen','UPDATE'], ['anon','profile_last_seen','DELETE'],
    ['anon','profile_last_seen','TRUNCATE'], ['anon','profile_last_seen','REFERENCES'],
    ['anon','profile_last_seen','TRIGGER'],
    ['authenticated','profile_last_seen','SELECT'], ['authenticated','profile_last_seen','INSERT'],
    ['authenticated','profile_last_seen','UPDATE'], ['authenticated','profile_last_seen','DELETE'],
    ['authenticated','profile_last_seen','TRUNCATE'], ['authenticated','profile_last_seen','REFERENCES'],
    ['authenticated','profile_last_seen','TRIGGER'],
    ['service_role','profile_last_seen','SELECT'], ['service_role','profile_last_seen','INSERT'],
    ['service_role','profile_last_seen','UPDATE'], ['service_role','profile_last_seen','DELETE'],
    ['service_role','profile_last_seen','TRUNCATE'], ['service_role','profile_last_seen','REFERENCES'],
    ['service_role','profile_last_seen','TRIGGER']
  ];

  -- Triples that MUST be granted. Just as important: a test that only asserts
  -- absence passes against a database where somebody revoked too much, and the
  -- symptom of that is a 42501 in production rather than a failing assertion.
  granted text[][] := array[
    -- Decision 6 in docs/ARCHITECTURE.md: profiles is the one browser-direct
    -- table, and a locked-out reader must still be able to read why.
    ['authenticated','profiles','SELECT'],
    ['service_role','profiles','SELECT'],
    ['service_role','app_settings','SELECT'],
    ['service_role','notification_recipients','SELECT'],
    -- admin_store.py:402 is the only direct write in all of web/.
    ['service_role','audit_log','INSERT'], ['service_role','audit_log','SELECT'],
    ['service_role','chat_sessions','SELECT'], ['service_role','chat_messages','SELECT'],
    ['service_role','chat_message_sources','SELECT'], ['service_role','chat_archive','SELECT'],
    -- The chat RLS policies are useless without the read grant behind them.
    ['authenticated','chat_sessions','SELECT'], ['authenticated','chat_messages','SELECT'],
    ['authenticated','chat_message_sources','SELECT'],
    -- Deleting a conversation IS browser-direct, and deliberately so: the
    -- chat_sessions_delete_own policy scopes it to the owner and to an active
    -- account, and the composite cascade takes the messages and sources with
    -- it — which is why neither of those tables needs a DELETE grant of its
    -- own. Asserted here so that revoking it "for consistency" fails loudly
    -- rather than silently breaking the sidebar.
    ['authenticated','chat_sessions','DELETE']
  ];

  -- The eleven columns 20260814005509 re-granted per column after revoking the
  -- table verbs. This is the boundary the profiles table revoke had to not
  -- break, and the interaction is the whole risk in that migration.
  writable_columns text[] := array[
    'id','first_name','family_name','age','organization','specialization',
    'preferences','marketing_consent','marketing_consent_language',
    'marketing_consent_policy_version','marketing_consent_surface'
  ];
  -- Server-owned. A trigger raises 42501 on these too, but the grant should
  -- never have been there in the first place.
  guarded_columns text[] := array[
    'role','tier','is_disabled','disabled_at','disabled_by','disabled_reason',
    'updated_at','full_name',
    'marketing_consent_granted_at','marketing_consent_withdrawn_at',
    'marketing_consent_granted_while_unconfirmed'
  ];

  t text[];
  c text;
begin
  foreach t slice 1 in array denied loop
    n := n + 1;
    if has_table_privilege(t[1], 'public.' || t[2], t[3]) then
      raise exception 'FAIL privileges — % holds % on public.%', t[1], t[3], t[2];
    end if;
  end loop;

  foreach t slice 1 in array granted loop
    n := n + 1;
    if not has_table_privilege(t[1], 'public.' || t[2], t[3]) then
      raise exception 'FAIL privileges — % LACKS % on public.%', t[1], t[3], t[2];
    end if;
  end loop;

  foreach c in array writable_columns loop
    n := n + 2;
    if not has_column_privilege('authenticated', 'public.profiles', c, 'UPDATE') then
      raise exception 'FAIL privileges — authenticated cannot UPDATE profiles.% — the '
        'table-level revoke took a column grant with it', c;
    end if;
    if not has_column_privilege('authenticated', 'public.profiles', c, 'INSERT') then
      raise exception 'FAIL privileges — authenticated cannot INSERT profiles.% — signup '
        'writes this column', c;
    end if;
  end loop;

  foreach c in array guarded_columns loop
    n := n + 1;
    if has_column_privilege('authenticated', 'public.profiles', c, 'UPDATE') then
      raise exception 'FAIL privileges — authenticated can UPDATE the server-owned '
        'column profiles.%', c;
    end if;
  end loop;

  -- The default ACLs themselves, which are what make all of the above durable
  -- for objects created after this was written. Two layers, and the difference
  -- between them is the whole of 20260828000737's post-apply correction:
  -- per-schema for tables, GLOBAL for the function EXECUTE-to-PUBLIC grant.
  n := n + 1;
  if exists (
    select 1 from pg_default_acl
     where defaclnamespace = 'public'::regnamespace
       and defaclobjtype = 'r'
       and pg_get_userbyid(defaclrole) = 'postgres'
       and defaclacl::text ~ '(anon|authenticated|service_role)='
  ) then
    raise exception 'FAIL privileges — the default table ACL in public grants to a '
      'browser or service role again; every new table is born writable';
  end if;

  -- NOT "a row must exist". Postgres DELETES a pg_default_acl row when the
  -- stored value returns to the hard-wired default, and the hard-wired TABLE
  -- default grants the owner only — no PUBLIC, no anon. So absence is a secure
  -- state and asserting presence would fail on it. What matters is the property
  -- checked above: no browser or service role appears in whatever default is in
  -- force.
  --
  -- FUNCTIONS ARE DIFFERENT, and are checked here rather than in
  -- function_acls.test.sql because this is the file about defaults. The
  -- hard-wired FUNCTION default grants EXECUTE to PUBLIC, so for functions the
  -- ABSENCE of an overriding entry is the open state. The override has to be
  -- GLOBAL (defaclnamespace = 0): a per-schema entry is merged onto the
  -- hard-wired base and cannot subtract PUBLIC from it. That is the mistake
  -- 20260828000737 made and 20260828100816 corrected.
  n := n + 1;
  if exists (
    select 1 from pg_default_acl
     where defaclnamespace = 0 and defaclobjtype = 'f'
       and pg_get_userbyid(defaclrole) = 'postgres'
       and defaclacl::text ~ '(^\{|,)=[a-zA-Z*]*X'
  ) then
    raise exception 'FAIL privileges — the global function default grants EXECUTE to '
      'PUBLIC again; every new function is born callable by any signed-in session';
  end if;

  n := n + 1;
  if not exists (
    select 1 from pg_default_acl
     where defaclnamespace = 0 and defaclobjtype = 'f'
       and pg_get_userbyid(defaclrole) = 'postgres'
  ) then
    raise exception 'FAIL privileges — there is no GLOBAL function default ACL for '
      'postgres, so the hard-wired default applies and every new function is born '
      'PUBLIC-executable. See 20260828100816.';
  end if;

  -- The DELETE grant above is only safe because of the policy behind it. A
  -- grant assertion alone would pass against a database where somebody dropped
  -- the policy, which is the state that would let any signed-in reader delete
  -- any conversation.
  n := n + 1;
  if not exists (
    select 1 from pg_policies
     where schemaname = 'public' and tablename = 'chat_sessions'
       and cmd = 'DELETE' and roles::text = '{authenticated}'
       and qual like '%owner_id%' and qual like '%is_active_account%'
  ) then
    raise exception 'FAIL privileges — chat_sessions has a DELETE grant for authenticated '
      'with no owner-and-active-scoped DELETE policy behind it';
  end if;

  summary := format('PASS privileges.test.sql — %s assertions', n);
  raise exception '%', summary;
end $$;
