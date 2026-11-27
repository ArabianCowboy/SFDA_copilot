-- Country on Accounts: one shared list of countries, a Country on every Profile,
-- and a counts-only answer for administrators.
-- ===========================================================================
-- Asked for by Thaqib (the other App on this project's Accounts): its plan is
-- ArabianCowboy/THAQIB docs/plans/accounts.md, decisions C168-C176, build spec
-- ArabianCowboy/THAQIB#34. Copilot's own sign-up asking Country is
-- ArabianCowboy/SFDA_copilot#17; until then copilot sign-ups get NULL, which is
-- valid.
--
-- Country means the country where the person lives or works, not nationality.
--
-- What this migration does, in order:
--   1. public.countries: 247 of the 249 ISO 3166-1 countries (code, English name),
--      readable by anyone (it is public data and Thaqib's sign-up page is
--      signed out), writable by nobody but the owner.
--   2. profiles.country: nullable, references countries(code) ON DELETE
--      RESTRICT, indexed; the reader may insert and update it (per-column
--      grants, as 20260814005509 set up for the other reader-owned columns).
--   3. handle_new_user: the whole latest body (20260823014034), unchanged,
--      plus Country read from the sign-up metadata (`country`, a 2-letter
--      code). Coerce, never raise: an unknown, malformed or missing code is
--      stored as NULL, so Country is never the reason an Account's creation
--      rolls back.
--   4. accounts_by_country(): counts only (country, count), for every Account,
--      NULL as one row; callable by authenticated, refuses anyone who is not
--      an enabled, active administrator. It is a fifth browser-callable
--      exception: function_acls.test.sql, privileges.test.sql,
--      country_on_accounts.test.sql and supabase/README.md change with it.
--
-- ROLLBACK, in this order. Dropping the column before restoring the trigger
-- would fail every sign-up, copilot's and Thaqib's:
--   1. drop function public.accounts_by_country();
--   2. re-run handle_new_user from 20260823014034 (from `create or replace
--      function public.handle_new_user()` through its revoke line);
--   3. alter table public.profiles drop column country;
--   4. drop table public.countries;
--
-- Names: ISO's short English names, with pycountry's common name where it has
-- one (Iran, South Korea, Syria, Taiwan, Viet Nam -> Vietnam, ...) and five
-- comma forms made readable (CD, FM, PS, VG, VI). Source: pycountry 26.2.16,
-- databases/iso3166-1.json. A renamed country is one UPDATE here; both Apps
-- read the table, neither keeps a copy.
--
-- LEFT OUT ON PURPOSE: IL and EH, by the owner's decision (2026-11-28), so the
-- list is 247 rows, not 249. Do not "fix" it back. A sign-up that sends either
-- code gets country NULL, like any code not on the list.

-- ---------------------------------------------------------------------------
-- 1. public.countries
-- ---------------------------------------------------------------------------
create table public.countries (
  code text primary key check (code ~ '^[A-Z]{2}$'),
  name text not null check (name = btrim(name) and length(name) between 1 and 100)
);

comment on table public.countries is
  'ISO 3166-1 countries (code, English name), shared by every App on this '
  'project. Read-only to clients; profiles.country references it.';

-- Thaqib turns the name a person picks back into its code, so a name must
-- name one country only, whatever its case.
create unique index countries_name_lower_key on public.countries (lower(name));

alter table public.countries enable row level security;

create policy countries_read_by_anyone on public.countries
  for select to anon, authenticated
  using (true);

-- The default privileges (20260828000737) give new tables nothing; revoke all
-- anyway (README: prefer `revoke all`), then grant the one verb clients need.
revoke all on public.countries from anon, authenticated, public, service_role;
grant select on public.countries to anon, authenticated;

insert into public.countries (code, name) values
  ('AD', 'Andorra'),
  ('AE', 'United Arab Emirates'),
  ('AF', 'Afghanistan'),
  ('AG', 'Antigua and Barbuda'),
  ('AI', 'Anguilla'),
  ('AL', 'Albania'),
  ('AM', 'Armenia'),
  ('AO', 'Angola'),
  ('AQ', 'Antarctica'),
  ('AR', 'Argentina'),
  ('AS', 'American Samoa'),
  ('AT', 'Austria'),
  ('AU', 'Australia'),
  ('AW', 'Aruba'),
  ('AX', 'Åland Islands'),
  ('AZ', 'Azerbaijan'),
  ('BA', 'Bosnia and Herzegovina'),
  ('BB', 'Barbados'),
  ('BD', 'Bangladesh'),
  ('BE', 'Belgium'),
  ('BF', 'Burkina Faso'),
  ('BG', 'Bulgaria'),
  ('BH', 'Bahrain'),
  ('BI', 'Burundi'),
  ('BJ', 'Benin'),
  ('BL', 'Saint Barthélemy'),
  ('BM', 'Bermuda'),
  ('BN', 'Brunei Darussalam'),
  ('BO', 'Bolivia'),
  ('BQ', 'Bonaire, Sint Eustatius and Saba'),
  ('BR', 'Brazil'),
  ('BS', 'Bahamas'),
  ('BT', 'Bhutan'),
  ('BV', 'Bouvet Island'),
  ('BW', 'Botswana'),
  ('BY', 'Belarus'),
  ('BZ', 'Belize'),
  ('CA', 'Canada'),
  ('CC', 'Cocos (Keeling) Islands'),
  ('CD', 'Democratic Republic of the Congo'),
  ('CF', 'Central African Republic'),
  ('CG', 'Congo'),
  ('CH', 'Switzerland'),
  ('CI', 'Côte d''Ivoire'),
  ('CK', 'Cook Islands'),
  ('CL', 'Chile'),
  ('CM', 'Cameroon'),
  ('CN', 'China'),
  ('CO', 'Colombia'),
  ('CR', 'Costa Rica'),
  ('CU', 'Cuba'),
  ('CV', 'Cabo Verde'),
  ('CW', 'Curaçao'),
  ('CX', 'Christmas Island'),
  ('CY', 'Cyprus'),
  ('CZ', 'Czechia'),
  ('DE', 'Germany'),
  ('DJ', 'Djibouti'),
  ('DK', 'Denmark'),
  ('DM', 'Dominica'),
  ('DO', 'Dominican Republic'),
  ('DZ', 'Algeria'),
  ('EC', 'Ecuador'),
  ('EE', 'Estonia'),
  ('EG', 'Egypt'),
  ('ER', 'Eritrea'),
  ('ES', 'Spain'),
  ('ET', 'Ethiopia'),
  ('FI', 'Finland'),
  ('FJ', 'Fiji'),
  ('FK', 'Falkland Islands (Malvinas)'),
  ('FM', 'Micronesia'),
  ('FO', 'Faroe Islands'),
  ('FR', 'France'),
  ('GA', 'Gabon'),
  ('GB', 'United Kingdom'),
  ('GD', 'Grenada'),
  ('GE', 'Georgia'),
  ('GF', 'French Guiana'),
  ('GG', 'Guernsey'),
  ('GH', 'Ghana'),
  ('GI', 'Gibraltar'),
  ('GL', 'Greenland'),
  ('GM', 'Gambia'),
  ('GN', 'Guinea'),
  ('GP', 'Guadeloupe'),
  ('GQ', 'Equatorial Guinea'),
  ('GR', 'Greece'),
  ('GS', 'South Georgia and the South Sandwich Islands'),
  ('GT', 'Guatemala'),
  ('GU', 'Guam'),
  ('GW', 'Guinea-Bissau'),
  ('GY', 'Guyana'),
  ('HK', 'Hong Kong'),
  ('HM', 'Heard Island and McDonald Islands'),
  ('HN', 'Honduras'),
  ('HR', 'Croatia'),
  ('HT', 'Haiti'),
  ('HU', 'Hungary'),
  ('ID', 'Indonesia'),
  ('IE', 'Ireland'),
  ('IM', 'Isle of Man'),
  ('IN', 'India'),
  ('IO', 'British Indian Ocean Territory'),
  ('IQ', 'Iraq'),
  ('IR', 'Iran'),
  ('IS', 'Iceland'),
  ('IT', 'Italy'),
  ('JE', 'Jersey'),
  ('JM', 'Jamaica'),
  ('JO', 'Jordan'),
  ('JP', 'Japan'),
  ('KE', 'Kenya'),
  ('KG', 'Kyrgyzstan'),
  ('KH', 'Cambodia'),
  ('KI', 'Kiribati'),
  ('KM', 'Comoros'),
  ('KN', 'Saint Kitts and Nevis'),
  ('KP', 'North Korea'),
  ('KR', 'South Korea'),
  ('KW', 'Kuwait'),
  ('KY', 'Cayman Islands'),
  ('KZ', 'Kazakhstan'),
  ('LA', 'Laos'),
  ('LB', 'Lebanon'),
  ('LC', 'Saint Lucia'),
  ('LI', 'Liechtenstein'),
  ('LK', 'Sri Lanka'),
  ('LR', 'Liberia'),
  ('LS', 'Lesotho'),
  ('LT', 'Lithuania'),
  ('LU', 'Luxembourg'),
  ('LV', 'Latvia'),
  ('LY', 'Libya'),
  ('MA', 'Morocco'),
  ('MC', 'Monaco'),
  ('MD', 'Moldova'),
  ('ME', 'Montenegro'),
  ('MF', 'Saint Martin (French part)'),
  ('MG', 'Madagascar'),
  ('MH', 'Marshall Islands'),
  ('MK', 'North Macedonia'),
  ('ML', 'Mali'),
  ('MM', 'Myanmar'),
  ('MN', 'Mongolia'),
  ('MO', 'Macao'),
  ('MP', 'Northern Mariana Islands'),
  ('MQ', 'Martinique'),
  ('MR', 'Mauritania'),
  ('MS', 'Montserrat'),
  ('MT', 'Malta'),
  ('MU', 'Mauritius'),
  ('MV', 'Maldives'),
  ('MW', 'Malawi'),
  ('MX', 'Mexico'),
  ('MY', 'Malaysia'),
  ('MZ', 'Mozambique'),
  ('NA', 'Namibia'),
  ('NC', 'New Caledonia'),
  ('NE', 'Niger'),
  ('NF', 'Norfolk Island'),
  ('NG', 'Nigeria'),
  ('NI', 'Nicaragua'),
  ('NL', 'Netherlands'),
  ('NO', 'Norway'),
  ('NP', 'Nepal'),
  ('NR', 'Nauru'),
  ('NU', 'Niue'),
  ('NZ', 'New Zealand'),
  ('OM', 'Oman'),
  ('PA', 'Panama'),
  ('PE', 'Peru'),
  ('PF', 'French Polynesia'),
  ('PG', 'Papua New Guinea'),
  ('PH', 'Philippines'),
  ('PK', 'Pakistan'),
  ('PL', 'Poland'),
  ('PM', 'Saint Pierre and Miquelon'),
  ('PN', 'Pitcairn'),
  ('PR', 'Puerto Rico'),
  ('PS', 'Palestine'),
  ('PT', 'Portugal'),
  ('PW', 'Palau'),
  ('PY', 'Paraguay'),
  ('QA', 'Qatar'),
  ('RE', 'Réunion'),
  ('RO', 'Romania'),
  ('RS', 'Serbia'),
  ('RU', 'Russian Federation'),
  ('RW', 'Rwanda'),
  ('SA', 'Saudi Arabia'),
  ('SB', 'Solomon Islands'),
  ('SC', 'Seychelles'),
  ('SD', 'Sudan'),
  ('SE', 'Sweden'),
  ('SG', 'Singapore'),
  ('SH', 'Saint Helena, Ascension and Tristan da Cunha'),
  ('SI', 'Slovenia'),
  ('SJ', 'Svalbard and Jan Mayen'),
  ('SK', 'Slovakia'),
  ('SL', 'Sierra Leone'),
  ('SM', 'San Marino'),
  ('SN', 'Senegal'),
  ('SO', 'Somalia'),
  ('SR', 'Suriname'),
  ('SS', 'South Sudan'),
  ('ST', 'Sao Tome and Principe'),
  ('SV', 'El Salvador'),
  ('SX', 'Sint Maarten (Dutch part)'),
  ('SY', 'Syria'),
  ('SZ', 'Eswatini'),
  ('TC', 'Turks and Caicos Islands'),
  ('TD', 'Chad'),
  ('TF', 'French Southern Territories'),
  ('TG', 'Togo'),
  ('TH', 'Thailand'),
  ('TJ', 'Tajikistan'),
  ('TK', 'Tokelau'),
  ('TL', 'Timor-Leste'),
  ('TM', 'Turkmenistan'),
  ('TN', 'Tunisia'),
  ('TO', 'Tonga'),
  ('TR', 'Türkiye'),
  ('TT', 'Trinidad and Tobago'),
  ('TV', 'Tuvalu'),
  ('TW', 'Taiwan'),
  ('TZ', 'Tanzania'),
  ('UA', 'Ukraine'),
  ('UG', 'Uganda'),
  ('UM', 'United States Minor Outlying Islands'),
  ('US', 'United States'),
  ('UY', 'Uruguay'),
  ('UZ', 'Uzbekistan'),
  ('VA', 'Holy See (Vatican City State)'),
  ('VC', 'Saint Vincent and the Grenadines'),
  ('VE', 'Venezuela'),
  ('VG', 'British Virgin Islands'),
  ('VI', 'U.S. Virgin Islands'),
  ('VN', 'Vietnam'),
  ('VU', 'Vanuatu'),
  ('WF', 'Wallis and Futuna'),
  ('WS', 'Samoa'),
  ('YE', 'Yemen'),
  ('YT', 'Mayotte'),
  ('ZA', 'South Africa'),
  ('ZM', 'Zambia'),
  ('ZW', 'Zimbabwe');

-- ---------------------------------------------------------------------------
-- 2. profiles.country
-- ---------------------------------------------------------------------------
-- profiles is read by every request in both Apps: fail fast rather than queue
-- behind a slow read and stall them (as 20260919013800 does). A timeout means
-- nothing was applied; run it again.
set local lock_timeout = '3s';

-- RESTRICT, typed out (README rule 8): a country that Profiles use cannot be
-- deleted from the list by accident.
alter table public.profiles
  add column country text references public.countries (code) on delete restrict;

comment on column public.profiles.country is
  'ISO 3166-1 code of the country where the person lives or works. NULL: not '
  'set (Accounts made before it, and sign-ups that did not send one).';

-- README rule 4: the foreign key's index, in the same migration. Partial,
-- because the foreign key's checks look up set values only.
create index profiles_country_idx on public.profiles (country)
  where country is not null;

-- Reader-owned, like organization and specialization: written through
-- PostgREST under the existing own-row RLS policies.
grant insert (country), update (country) on public.profiles to authenticated;

-- ---------------------------------------------------------------------------
-- 3. handle_new_user: 20260823014034's body, plus Country
-- ---------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_meta           jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
  v_age_text       text;
  v_age            integer;
  v_first_name     text;
  v_family_name    text;
  v_consent        boolean := false;
  v_policy_version text;
  v_language       text;
  v_country        text;
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

  if jsonb_typeof(v_meta -> 'marketing_consent') = 'boolean' then
    v_consent := (v_meta ->> 'marketing_consent')::boolean;
  end if;

  v_policy_version :=
    nullif(left(btrim(v_meta ->> 'marketing_consent_policy_version'), 64), '');

  v_language :=
    case v_meta ->> 'marketing_consent_language'
      when 'en' then 'en'
      when 'ar' then 'ar'
      else null
    end;

  -- A boolean without the disclosure version and language is not an
  -- adequate consent record. Coerce it to a decline rather than aborting
  -- signup.
  if v_consent
     and (v_policy_version is null or v_language is null) then
    v_consent := false;
  end if;

  -- The signup UI gates age behind consent. A direct GoTrue caller cannot
  -- bypass that collection rule by submitting age with consent=false.
  if not v_consent then
    v_age := null;
  end if;

  -- Country: only a code that is on the list. No row found leaves NULL, so a
  -- bad value can never fail the foreign key and roll back the sign-up.
  -- ASCII letters first: upper() would turn 'ſa' into 'SA'.
  if jsonb_typeof(v_meta -> 'country') = 'string'
     and v_meta ->> 'country' ~ '^ *[A-Za-z]{2} *$' then
    select c.code into v_country
      from public.countries c
     where c.code = upper(btrim(v_meta ->> 'country'));
  end if;

  insert into public.profiles (
    id, first_name, family_name, age, role,
    organization, specialization, preferences,
    marketing_consent,
    marketing_consent_policy_version,
    marketing_consent_language,
    marketing_consent_surface,
    country
  )
  values (
    new.id, v_first_name, v_family_name, v_age, 'user',
    '', '', '{"theme": "system"}'::jsonb,
    v_consent,
    case when v_consent then v_policy_version end,
    case when v_consent then v_language end,
    case when v_consent then 'signup' end,
    v_country
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

revoke execute on function public.handle_new_user()
  from anon, authenticated, public;

-- ---------------------------------------------------------------------------
-- 4. accounts_by_country(): counts only, administrators only
-- ---------------------------------------------------------------------------
-- Called by Thaqib's admin page with the administrator's own session, so it
-- reads auth.uid() (copilot's admin_* RPCs are service_role-only, called by
-- Flask behind its admin gate). Every Account counts, from auth.users, so an
-- Account without a Profile row still lands in the NULL row. No names, no
-- emails, no ids. An admin whose own deletion is `pending` still passes:
-- pending is active (20260918234407), and Thaqib's C174 relies on that.
create or replace function public.accounts_by_country()
returns table (country text, count bigint)
language plpgsql
stable
security definer
set search_path = ''
as $$
#variable_conflict use_column
begin
  -- One refusal for "no session", "not an administrator", "disabled" and
  -- "frozen by a deletion": the caller has no business telling them apart.
  if not exists (
       select 1
         from public.profiles p
        where p.id = auth.uid()
          and p.role = 'admin'
          and p.is_disabled = false)
     or not public.is_active_account() then
    raise exception 'an enabled administrator is required'
      using errcode = '42501';
  end if;

  return query
    select p.country, pg_catalog.count(*)::bigint
      from auth.users u
      left join public.profiles p on p.id = u.id
     group by p.country
     order by 2 desc, 1 nulls last;
end;
$$;

comment on function public.accounts_by_country() is
  'Accounts per profiles.country (NULL: not set), counts only, every Account. '
  'Browser-callable by authenticated for Thaqib''s admin page; refuses anyone '
  'who is not an enabled, active administrator (42501).';

revoke execute on function public.accounts_by_country()
  from public, anon;
grant execute on function public.accounts_by_country() to authenticated, service_role;
