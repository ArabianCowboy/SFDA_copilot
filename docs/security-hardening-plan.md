STATUS: PARTIALLY EXECUTED — Tasks 1 and 2 shipped 2026-08-27 (`366f1a6`, `d9e542c`);
Tasks 3 and 4 still open, blocked as described below. Written 2026-08-26.

# Security hardening plan: four TODO entries

Four `TODO.md` entries, planned together because two of them ship as code and two are
verification work whose answers live outside this repository. Every `file:line` below was read
in the session that wrote this. Where a claim could not be verified here, it says so.

Supersedes nothing. When each item lands, close its `TODO.md` entry and update this file's
`STATUS:` line; when all four are done, archive this file per
[`docs/archive/README.md`](archive/README.md#adding-to-this-archive).

---

## Summary

| #   | Task                                    | Verdict                                                     | Ships as            |
| --- | --------------------------------------- | ----------------------------------------------------------- | ------------------- |
| 1   | Tighten CSP `img-src` to `'self' data:` | Safe — the image surface is provably same-origin or `data:` | Code + test         |
| 2   | Reorder the signup request spread       | Correctness fix, not a vulnerability                        | Code + test         |
| 3   | Notification-center auth, end to end    | Needs live Supabase credentials                             | Verification + docs |
| 4   | `/c/<uuid>` access-log retention        | Two log surfaces, not one — see below                       | Docs only           |

---

## Task 1 — Tighten `img-src` to `'self' data:`

**Where:** `web/api/app.py:1364`, inside the `csp` dict that begins at `web/api/app.py:1347`.

### Why this is worth more than the TODO entry argues

`TODO.md` files this as a `Referer`-leak defence: an `<img>` to a foreign host would carry
`/c/<uuid>` in the referrer. **That premise does not hold.** Talisman already sets
`referrer_policy="strict-origin-when-cross-origin"` at `web/api/app.py:1400`, which strips path
and query from every cross-origin request. The conversation id was never in that header.

The real, unmitigated vector is different. Model output is rendered through `marked` and then
`DOMPurify.sanitize(html, { USE_PROFILES: { html: true } })` — `static/js/modules/stream-render.js:19-25,102-145`
and `static/js/modules/ui.js:19-26`. **The `html` profile permits `<img>`.** So markdown
`![x](https://attacker/beacon.png)` **in a model answer** is a live outbound GET today,
disclosing viewer IP, request timing, and DNS/SNI to whoever owns that host. `img-src` is what
closes it.

**Scope that claim precisely: the answer body is the only such path.** The two adjacent surfaces
are already safe, and this plan should not imply otherwise. Citation markers are built with
`createElement` _after_ the markdown is sanitized, so DOMPurify never sees them and no attacker
text is re-parsed (`static/js/modules/citations.js:13-16`). Corpus fields reach the source panel
through `textContent`, not `innerHTML` (`static/js/modules/source-panel.js:264-268,404-428`). A
retrieved chunk can therefore only reach an `<img>` by first passing through the model and coming
back out as answer markdown — which is exactly the path this directive closes.

Do the task. Fix the reasoning in the entry when you close it.

### The image surface, enumerated

`TODO.md` asks for a real enumeration rather than a guessed replacement list. This is it.
**Nothing in any template loads an image from any external origin.**

| Asset                       | Referenced at                                                                                          | Origin                       | Directive                 |
| --------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------- | ------------------------- |
| `favicon.svg`               | `index.html:15`, `admin.html:22`, `account.html:23`, `privacy.html:16`                                 | `'self'`                     | `img-src`                 |
| `favicon.png`               | `index.html:16` (alternate), `index.html:18` (apple-touch)                                             | `'self'`                     | `img-src`                 |
| `favicon.ico`               | `index.html:17`, `admin.html:23`, `account.html:24`, `privacy.html:17`; route at `web/api/app.py:2129` | `'self'`                     | `img-src`                 |
| Close-button glyph          | `static/css/components.css:376`, masked at `:394-395`                                                  | `data:`                      | `img-src`                 |
| Bootstrap 5.3.0 control art | `index.html:36`, `admin.html:30`, `account.html:31`, `privacy.html:24` (jsDelivr)                      | 23 `url(`, **0 non-`data:`** | `img-src`                 |
| Sunny and every icon        | `web/utils/icons.py` (zero `http` occurrences), `static/js/modules/robot.js`                           | inline SVG                   | none — no fetch           |
| Sidebar chrome              | `web/templates/partials/_sidebar.html:22,45,121,133,141,144`                                           | `icon()` → inline SVG        | none — no fetch           |
| Google Fonts                | `index.html:26-29`                                                                                     | `fonts.gstatic.com`          | `font-src`                |
| AI Fouda Hub, LinkedIn      | `index.html:485-486`                                                                                   | external                     | `<a href>` — not governed |

**There are five templates, not three.** `web/templates/partials/_sidebar.html` is a partial the
top-level pages include, and an inventory that stops at `web/templates/*.html` misses it. It
turns out to reference nothing but `icon()`, so the verdict is unchanged — but the verdict now
rests on having looked, rather than on the partial happening to be clean.

The enumeration was closed with one sweep across all five templates plus `static/js/` and
`static/css/` for every image-bearing construct — `<img`, `srcset=`, `<image>`, `poster=`,
`type="image"`, `image-set(`, `mask-image`, `list-style-image`, `cursor: url(`, `content: url(`,
`background-image: url(`, `.src =`, `new Image(`. It returns **nothing** beyond the table above.

The Bootstrap row is measured, not assumed: the pinned CDN stylesheet was fetched and its
`url(` tokens counted. All 23 are `data:image/svg+xml`.

There is no `<img>` anywhere in `static/js/`, no `<meta http-equiv>` CSP in any template, and no
`@talisman` per-view override anywhere in `web/` — so the dict at `web/api/app.py:1347` is the
single source of this policy. (Talisman does support per-view overrides via its decorator; this
repo simply does not use them. Confirmed against the flask-talisman documentation.)

**Adjacent dead configuration.** `https://cdn.lordicon.com` sits in both `script-src` and
`connect-src` (`web/api/app.py:1327, 1353`) but no `lord-icon` element or reference exists in any
template or module. Out of scope here — removing it is a separate change with its own blast
radius, and a silent drive-by removal inside a security commit is exactly the kind of edit that
is hard to review.

**But something has to carry it.** Open a new `TODO.md` entry for it as part of Commit A's
close-out, in the same commit that closes this one. A discovery that lives only in a plan
document is a discovery that gets archived and lost.

### The change

```diff
--- a/web/api/app.py
+++ b/web/api/app.py
@@
-        "img-src": ["'self'", "data:", "https:"],
+        # No external image is loaded anywhere: favicons are same-origin, every
+        # icon is inline SVG (web/utils/icons.py), and Bootstrap's control art is
+        # data: URIs. The wildcard mattered because model output renders through a
+        # DOMPurify profile that permits <img> (stream-render.js:24), which made a
+        # markdown image in an answer an outbound beacon.
+        "img-src": ["'self'", "data:"],
```

**The debug branch stays untouched.** `web/api/app.py:1376-1382` loosens `font-src` and
`connect-src` for browser extensions; images are deliberately not in that precedent. Relaxing
`img-src` in debug would let a dev environment silently pass what production blocks — the
opposite of what a verification matrix run locally is meant to establish.

**`ASSET_VERSION` is not bumped.** It lives at `web/api/app.py:249`, and CLAUDE.md's rule binds
it to commits touching CSS or JS. This commit touches neither. If this change is ever bundled
into a commit that also touches CSS or JS, the bump comes back with that other change.

### The test

There is no CSP test in `web/tests/` today — confirmed. New file
`web/tests/test_security_headers.py`.

Note that `create_app(testing=True)` (`web/api/app.py:3275`) takes the permissive debug branch,
so the test asserts the one directive that branch does not touch. The live header string was
captured to pin the exact format:

```text
default-src 'self'; script-src ...; style-src ...;
img-src 'self' data: https:; font-src 'self' https: data:;
connect-src 'self' https: wss: http://localhost:8400
```

```python
from web.api.app import create_app


def _directives(response):
    """Talisman joins directives with "; " and tokens within one with " ".

    `partition` rather than `split(" ", 1)[1]`: a valueless directive — a future
    `upgrade-insecure-requests` — has no space to split on and would raise
    IndexError, failing this test for a reason unrelated to what it asserts.
    flask-talisman is unpinned (requirements.txt:4), so its serialization is not
    frozen by this repo and the parser should not assume more than it must.
    """
    policy = response.headers["Content-Security-Policy"]
    return {name: value for name, _, value in (part.partition(" ") for part in policy.split("; "))}


def test_img_src_admits_only_same_origin_and_data_uris():
    """No wildcard host. An image request the product did not author must not be
    able to leave the origin — see stream-render.js, which renders model output
    through a DOMPurify profile that permits <img>."""
    client = create_app(testing=True).test_client()

    directives = _directives(client.get("/"))

    assert directives["img-src"] == "'self' data:"


def test_the_debug_branch_does_not_loosen_img_src():
    """testing=True takes the permissive branch (app.py:1376-1382). That branch is
    font-src and connect-src only, deliberately."""
    client = create_app(testing=True).test_client()

    directives = _directives(client.get("/"))

    assert "https:" not in directives["img-src"]
```

Both fail today against `'self' data: https:`. Neither mocks the thing under test — they read
the header a browser will actually receive.

### Manual verification: all twelve permutations

**Theme is not a URL parameter.** `static/js/modules/theme.js:16,37` reads and writes
`localStorage.theme`, reflected as `data-bs-theme`. So each row is: set the key, then load.
Start the app with `FLASK_TESTING=true python web/api/app.py` and watch the console for
`Refused to load the image`.

| #   | Page    | Lang | Theme | URL, after setting `localStorage.theme` |
| --- | ------- | ---- | ----- | --------------------------------------- |
| 1   | Landing | EN   | Light | `/?testing=true`                        |
| 2   | Landing | EN   | Dark  | `/?testing=true`                        |
| 3   | Landing | AR   | Light | `/?lang=ar&testing=true`                |
| 4   | Landing | AR   | Dark  | `/?lang=ar&testing=true`                |
| 5   | Account | EN   | Light | `/account?testing=true`                 |
| 6   | Account | EN   | Dark  | `/account?testing=true`                 |
| 7   | Account | AR   | Light | `/account?lang=ar&testing=true`         |
| 8   | Account | AR   | Dark  | `/account?lang=ar&testing=true`         |
| 9   | Admin   | EN   | Light | `/admin?testing=true`                   |
| 10  | Admin   | EN   | Dark  | `/admin?testing=true`                   |
| 11  | Admin   | AR   | Light | `/admin?lang=ar&testing=true`           |
| 12  | Admin   | AR   | Dark  | `/admin?lang=ar&testing=true`           |

Run this in a clean browser profile or with extensions disabled. An extension that injects an
image will produce a CSP violation that is not the product's, and mistaking one for the other
wastes the sweep.

**Two surfaces the "three pages" framing misses.** There are four templates, and `/c/<uuid>` is
a fifth route. `privacy.html` carries the same favicon and Bootstrap set (`privacy.html:16-25`),
and `/c/<uuid>` renders the identical shell via `_render_shell()` at `web/api/app.py:2023-2051`.
Add two spot checks — `/privacy?lang=ar&testing=true` and any `/c/<uuid>` — so the enumeration
matches the deployed surface rather than the count in the entry.

**Expected, not a regression.** After this lands, a model answer containing a remote markdown
image will log a CSP violation and render a broken-image box. That is the fix working. Do not
mistake it for a defect during the sweep, and do not add the host back.

---

## Task 2 — Explicit signup fields must survive a metadata collision

**Where:** `static/js/modules/services.js:384`, inside `Services.signup()` at
`static/js/modules/services.js:379`.

### What is actually at stake

This is a **correctness fix, not a security fix**, and the plan should say so plainly.

The single call site — `static/js/modules/handlers.js:249-265`, the only `Services.signup(`
caller in the tree — builds its metadata from six literal keys, never from a form loop or
`Object.fromEntries`. No reader input can introduce a colliding key. And a hostile client can
post any JSON body it likes regardless of what this function does.

What the reorder buys is that the next person to add a metadata field cannot silently break
signup. `SIGNUP_METADATA_KEYS` (`web/api/auth.py:43-50`) is `first_name`, `family_name`,
`marketing_consent`, `marketing_consent_policy_version`, `marketing_consent_language`, `age` —
none collide today. The server allow-list governs only what reaches `raw_user_meta_data`; it
does not guard the top-level fields this spread can clobber.

**No server-side guard is warranted.** `web/api/auth.py` reads `email`, `password`, and `lang`
directly from the top level of the parsed body and forwards metadata separately through
`_signup_metadata(data)` (`web/api/auth.py:126`). A colliding metadata key is forwarded as
metadata only, never atop a credential. There is nothing on the server for a collision guard to
protect.

### The change

```diff
--- a/static/js/modules/services.js
+++ b/static/js/modules/services.js
@@
-      body: JSON.stringify({ email, password, lang, ...metadata }),
+      body: JSON.stringify({ ...metadata, email, password, lang }),
```

The JSDoc immediately above (`static/js/modules/services.js:370-378`) explains the metadata
contract but says nothing about precedence, which is now the load-bearing property. Extend it
rather than rewriting it — the existing text about `handle_new_user` coercing toward null is
still true and still worth keeping:

```diff
    * server allow-lists which of these keys it forwards, so this is no longer
    * the only validation the way the docstring here used to warn — but keep
    * sending only what belongs in `raw_user_meta_data` regardless.
+   *
+   * `metadata` spreads FIRST so the explicit arguments win a collision. A
+   * metadata key named `email`, `password` or `lang` would otherwise overwrite
+   * the real value with no error surfaced anywhere.
    */
```

**`ASSET_VERSION` at `web/api/app.py:249` must be bumped** — this commit touches JS.

### The `undefined lang` question, settled

This is the one regression the reorder could introduce, and it does not fire.

`lang` is the fourth positional parameter with no default, so a caller omitting it passes
`undefined`; under the new order that `undefined` wins, and `JSON.stringify` drops the key
entirely. It is harmless on both ends:

- The only caller passes `I18n.lang` explicitly (`static/js/modules/handlers.js:264`), which
  resolves to `window.__LANG || 'en'` and is therefore always a string.
- The server tolerates the key's absence anyway. `web/api/auth.py` reads `data.get("lang")` →
  `None`, and its guard is `isinstance(lang, (str, type(None)))`, which admits `None`.
  `signup_redirect_url(None)` then omits the query parameter rather than raising.

No guard is needed.

### The regression test

`web/tests/test_signup_identity_capture.py:23-39` already has a `signup_capture` fixture that
routes `**/auth/signup` and records `route.request.post_data_json`. `web/tests/conftest.py:594-601`
mocks the supabase CDN import at _context_ level, and `static/js/modules/services.js:6` is that
module's only external import — so the module loads cleanly in page context. The import map at
`web/api/app.py:1957-1966` keys real static URLs, so a dynamic import resolves to the versioned
module.

A real runtime test is therefore available, and it is the one to take. Add it beside
`test_signup_sends_both_names_as_signup_metadata` (`web/tests/test_signup_identity_capture.py:80`):

```python
def test_explicit_signup_fields_survive_a_colliding_metadata_key(
    browser_page: Page, signup_capture
):
    """A metadata key named `email`, `password` or `lang` must lose to the real
    argument. The signup form cannot produce such a key — handlers.js:249-265
    sends six literal keys — so this drives Services.signup directly, which is
    where a future caller would introduce the collision."""
    browser_page.goto("/")

    browser_page.evaluate(
        """async () => {
            const { Services } = await import('/static/js/modules/services.js');
            await Services.signup(
              'real@example.com',
              'RealPass1',
              { email: 'attacker@example.com',
                password: 'wrong',
                lang: 'zz',
                first_name: 'Amina' },
              'ar',
            );
        }"""
    )

    assert len(signup_capture) == 1
    sent = signup_capture[0]
    assert sent["email"] == "real@example.com"
    assert sent["password"] == "RealPass1"
    assert sent["lang"] == "ar"
    assert sent["first_name"] == "Amina"  # metadata still arrives
```

Against the current code the metadata spread wins and all three explicit assertions fail —
verify that before believing the test, per CLAUDE.md.

It is marked `browser`, so it runs in the second CI job (`pytest -m browser --browser chromium`),
not the fast one. If the fast job should hold the line too, add a one-line source-text assertion
in `web/tests/test_frontend_architecture.py` as a cheap companion — but the runtime test is the
one that proves the behaviour.

---

## Task 3 — Notification-center auth, against a live Supabase project

**Where:** no code change expected. `TODO.md` names this the one check owed before the feature
ships to production.

### One suspected defect, cleared by reading the SDK

The open worry was whether the private Realtime channel re-authorizes after a token refresh —
`Notifications.subscribe` (`static/js/modules/services.js:930-939`) never calls `setAuth` itself.

**It does not need to.** `SupabaseClient.js:207-225` registers an internal auth listener whose
`_handleTokenChanged` calls `realtime.setAuth(token)` on `TOKEN_REFRESHED` and `SIGNED_IN`, and
clears it on `SIGNED_OUT`. Combined with `autoRefreshToken: true`
(`static/js/modules/services.js:151`), refresh is handled by the SDK.

**On the strength of that evidence.** The file read is under `node_modules/`, which this repo
keeps as dev-only tooling — `package.json:2` states plainly that there is no bundler and no
runtime `node_modules`, and the browser loads the SDK from jsDelivr. It is still good evidence
because the versions are pinned in lockstep by policy: `package.json:5` and the CDN URL at
`static/js/modules/services.js:6` are both `2.74.0`, and that file's own comment requires them to
be kept in sync. It is not the artefact the browser executes, so treat it as a strong prior, not
as proof.

Confirm it empirically at step 11 — but it is no longer a suspected bug, which changes what this
end-to-end run is for.

**Initial session is a separate case.** `_handleTokenChanged` fires on `TOKEN_REFRESHED` and
`SIGNED_IN`; the first authorization of the channel on a fresh page load is covered by step 4,
not step 11. Do not let a passing step 11 stand in for it.

### The auth path being exercised

| Stage              | Location                                         | Behaviour under test                                          |
| ------------------ | ------------------------------------------------ | ------------------------------------------------------------- |
| Token extraction   | `web/api/app.py:305`                             | Bearer header → `sb-access-token` cookie → Flask session      |
| Resolution         | `web/api/app.py:530`                             | `supabase.auth.get_user(token)` on every request              |
| Outage vs refusal  | `web/api/app.py:456-488, 582`                    | Outage → **503, session intact**. Refusal → 401. Fault → 500. |
| Role freshness     | `web/api/app.py:561-570`                         | 30s TTL for readers; `fresh=True` for the admin blueprint     |
| Identity swap      | `web/api/app.py:334-353` → `web/api/auth.py:104` | `rotate_session_for_new_identity()` on a changed reader       |
| Cache              | `web/services/identity_cache.py:105-118`         | TTL + LRU bound                                               |
| Failure not cached | `web/services/admin_store.py:866-891`            | a failed lookup must not pin a wrong role for 30s             |
| Reader routes      | `web/api/app.py:2699, 2729, 2784, 2829`          | active, history, mark-read, mark-all-read                     |
| Admin gate         | `web/api/admin.py:61-131`                        | bearer required, administrator revalidated                    |
| Realtime           | `static/js/modules/services.js:930-939`          | `notify:user:<id>`, `{ private: true }`                       |
| REST reconcile     | `static/js/modules/handlers.js:1114`             | `setInterval(tick, 45000)` — the guaranteed path              |

### What the runner needs

Names only, never values.

**Required** — all documented in `.env.example`:

- `SUPABASE_URL`, `SUPABASE_ANON_KEY` (`web/utils/config_loader.py:131,136`), `SUPABASE_PROJECT_REF`
- `SUPABASE_SECRET_KEY` or legacy `SUPABASE_SERVICE_ROLE_KEY` (`web/utils/supabase_client.py:126`)
- `FLASK_SECRET_KEY`, `PUBLIC_BASE_URL`

**Optional overrides, not needed for the run** — both already have working defaults, so do not
treat their absence as a blocker: `SUPABASE_AUTH_TIMEOUT` (default at
`web/utils/supabase_client.py:36`, documented in `README.md:243-252`) and
`SUPABASE_REALTIME_TIMEOUT` (default at `web/services/notification_service.py:35-40`, not
documented in `.env.example`).

**Accounts:** two distinct enabled readers and one administrator, plus SQL-editor access for
cleanup.

**Three gates will block account creation if unnoticed.**

- **Registrations pause** — `signup_enabled` at `web/config.yaml:26`, overridable from the
  console. A paused instance answers `403 signup_disabled` before any provider call.
- **Rate limit** — `signup_api: "5 per minute"` at `web/config.yaml:123`.
- **Confirm email** must stay on (see `docs/OPERATIONS.md`): signup is server-mediated and
  returns no session, so each test account needs its confirmation link followed, or confirming
  through the Admin API. (Read in the dashboard 2026-09-06: it is on. This is no longer an open
  question to settle during the run — `TODO.md` had folded that probe into this trip, and it has
  since been answered and archived.)
- **The mail ceiling is 30 emails per hour, per project** — `docs/OPERATIONS.md:76-81`, and it is
  enforced by Supabase independently of Resend's own limits. Three accounts plus any password
  resets is comfortably inside it, but a repeated run in the same hour is not. Create the
  accounts once, early, and reuse them across attempts rather than re-creating per attempt.

### The checklist

1. Run production-shaped:
   `gunicorn --workers 1 --threads 8 --timeout 300 "web.api.app:create_app()"` against the live project.
2. Create reader A, reader B, and an admin. Confirm each, enable each, grant the admin role.
3. Sign in as A. `GET /api/identity` with A's bearer token returns A (`web/api/app.py:2164`).
4. With A's page open, confirm the WebSocket reaches `SUBSCRIBED` on `notify:user:<A>`
   (`static/js/modules/services.js:930-939`).
5. As admin, broadcast a bilingual notification from `/admin` (`web/api/admin.py:61-131` gates it).
6. Assert A receives a broadcast carrying **only** `{notification_id, revision}`, then refetches
   over REST. Content must never ride the channel.
7. With B offline, target B; bring B online; assert `GET /api/notifications/active` delivers it
   (`web/api/app.py:2699`).
8. As A, assert B's notifications and receipts are absent from both `/active` and `/history`.
9. As A, `POST /api/notifications/mark-read` for a B-targeted id. Assert refusal and no row
   written (`web/api/app.py:2784`).
10. Mark a legitimate one read; assert the receipt is visible to A only.
11. **Force a token refresh** with the page open, then assert the channel still delivers a
    freshly broadcast notification. The client is not on `window` in a production build — it is
    exposed only under debug (`static/js/modules/services.js:132-160`) — so pick a repeatable
    trigger and record which one was used. **Try the levers in this order, and stop at the first
    that works:**

    1. Run this leg with debug on and call `refreshSession()` directly. Contained to your own
       session; no blast radius. Prefer it.
    2. Only if (1) is impossible: shorten the project's JWT expiry in the Supabase dashboard.
       **This retunes token lifetime for every live session on the project until reverted** — it
       is not a local change. Do it inside a maintenance window, write the original value into
       the run record _before_ changing it, and revert as the first action after the step passes.

    **Required evidence:** a `TOKEN_REFRESHED` event in the console, a new access token on the
    wire, and a post-refresh `SUBSCRIBED` with delivery. "It still seemed to work" is not a pass.

12. **Induce the outage on the application host, not the browser.** The auth call under test is
    server-side — `supabase.auth.get_user(token)` runs inside the Flask/gunicorn process
    (`web/api/app.py:546-582`), so blocking the Supabase host in the browser exercises nothing.
    Block it from the app host (firewall rule, `/etc/hosts` null-route, or drop egress to the
    project domain), then call `/api/notifications/active` with a valid bearer token. Assert
    **503, not 401**, and that the session survives (`web/api/app.py:456-488, 571-593`).

    **Write the exact block command and its exact reversal into the run record before executing
    either.** This step deliberately breaks a production host's egress; the reversal must be
    decided in advance, not improvised while the service is down. If the host serves real
    readers, do this in a maintenance window or against a staging project instead — and say in
    the verification note which one you used, because the two are not equivalent evidence.

13. Restore connectivity; assert the next GET succeeds without a re-login.
14. Demote the admin mid-operation; assert the RPC rejects with `actor_no_longer_administrator`.
15. Sign out; assert the channel is torn down and no stale conversation reaches the next reader
    on the same browser.
16. Delete the test notifications and accounts. Record ids, timestamps, and statuses — never
    tokens or credentials.

### What a mock cannot establish

Steps 6, 9, 11, 12 and 14 are the ones worth the credentials. A mock cannot prove GoTrue
signature validation or refresh-token rotation, cannot prove `realtime.messages` RLS admits A's
topic and refuses B's, cannot prove a real outage classifies as 503, and cannot prove the
service-role publish endpoint accepts the private-channel request shape.

The prior session's live session-variable RLS simulation covers the database leg only — it says
nothing about the browser auth leg.

### Recording the result

- `docs/notification-center-plan.md` — advance the `STATUS:` line and add a dated
  live-verification section.
- `TODO.md` — replace "that one check is still owed before this ships to production" with the
  date, the environment class, and anything deferred. Then move the entry through the archive
  procedure in [`docs/archive/README.md`](archive/README.md#adding-to-this-archive) and delete
  its index line.
- The unrelated `mypy`/numpy stub failure reproduces on clean `main` and does **not** block this
  item. Say so rather than leaving it ambiguous.

---

## Task 4 — Whether `/c/<uuid>` survives in the access log

**Where:** documentation only, on the scope as filed. The `TODO.md` entry is right that no
application change is needed _for the access log_ — but it frames the task as one surface when
there are two, and the second one is application code. See below before accepting the framing.

### There are two log surfaces here, not one

The `TODO.md` entry is written as though the only question were the **HTTP access log**. It is
not. This application writes conversation ids into its **own** logs at roughly a dozen sites, and
one of them is not a failure path at all:

| Site                                    | Level    | When                                                  |
| --------------------------------------- | -------- | ----------------------------------------------------- |
| `web/api/app.py:3093`                   | **INFO** | **client disconnects mid-stream — an ordinary event** |
| `web/api/app.py:725`                    | WARNING  | hydration failed                                      |
| `web/api/app.py:1050`, `:1087`, `:1096` | ERROR    | turn not durably recorded / persist failed            |
| `web/api/app.py:1111`                   | —        | replayed `client_request_id`                          |
| `web/api/app.py:1147`                   | —        | preflight could not run                               |
| `web/api/app.py:2363`, `:2393`          | WARNING  | existence check / transcript hydration failed         |
| `web/api/app.py:2597`, `:2651`          | WARNING  | rename / delete failed                                |
| `web/api/app.py:3099`, `:3108`          | ERROR    | retrieval / streaming failed                          |

`app.py:3093` is the one that changes the shape of this task. A reader closing a tab mid-answer
is normal traffic, so conversation ids land in the application log at `INFO` under routine use —
not only when something breaks. With `logging.level: INFO` (`web/config.yaml:283-284`) that path
is live in production.

**So the OPERATIONS.md section must cover both surfaces**: the HTTP access log (owned by the
proxy and the WSGI server) and the application log (owned by this code, but retained by whatever
captures stderr — journald, a file, or a forwarder). They have different owners, different
retention, and possibly different readers. Answering only the first one leaves the question open.

### What this repository configures

Nothing at the HTTP layer. There is no nginx config, no gunicorn config, no systemd unit, no
Dockerfile, no APM SDK, and no log-export configuration anywhere in the tree.

- `web/api/app.py:108-116` — `LOG_LEVEL` and a `basicConfig` to stderr; `web/config.yaml:282-285`
  mirrors level and format. **This is where the conversation ids above go**, and nothing here
  says where stderr is captured or how long it is kept.
- `web/api/app.py:121-125` — a `RotatingFileHandler` example, commented out and inactive.
- `README.md:100-110` and `docs/ARCHITECTURE.md:137-145` give operators an nginx snippet — but
  for `proxy_buffering off`, not access logging.

Everything that _retains_ either surface lives in the deployment. That is precisely why the
answer belongs in `docs/OPERATIONS.md`.

**The repo hints at the deployment shape**, which narrows the questions worth asking. `gunicorn`
is a dependency (`requirements.txt:6`, unversioned), and `README.md:95` /
`docs/ARCHITECTURE.md:104` give an invocation carrying **no** `--access-logfile` — so gunicorn is
likely not writing an access log at all. `BEHIND_PROXY` exists to gate `ProxyFix`
(`web/api/app.py:1292-1304`, default `false` at `.env.example:45`), which is only useful when
something terminates TLS upstream.

Treat that as a reason to **ask about nginx first**, not as evidence that nginx is there. This
repository cannot establish the live topology, and the plan should not pretend otherwise.

### The threat-model claim, checked

The `TODO.md` claim holds, with **one wording correction that must carry into the write-up**.

The route (`web/api/app.py:2086-2127`) **never queries conversation data** with the id. It does
read it — to canonicalise case and compare against the raw path (`web/api/app.py:2115-2121`) —
so "never reads the id" is the wrong claim to make; "never looks it up" is the right one. It then
renders the same shell `/` renders. Pinned by `web/tests/test_deep_link_contract.py`: no auth
(`:255`), no `Set-Cookie` (`:261`), invariant response (`:267`), 301 to canonical case (`:277`),
`X-Robots-Tag: noindex, nofollow` (`:287`).

**Do not repeat the entry's phrasing.** `TODO.md` says the response is "byte-identical for a
foreign id and for one that never existed". The test that pins this compares two _arbitrary_
UUIDs, and its own docstring at `:267-270` explicitly narrows the claim: _"the
no-existence-oracle property (§3.1), narrower than and correcting the round-1 draft's
'byte-identical for any reader'"_. The property is real — the route ignores the id — but the
`docs/OPERATIONS.md` section must use the narrower wording, or it re-introduces a claim this
repository already corrected once.

**Residual disclosure, as far as this repository can establish it:** the id identifies a
conversation and nothing more — it grants no access to identity, question text, answer, or
citations, because nothing accepts it as a credential. What a _log line_ additionally reveals —
which fields are captured, whether a reader IP sits beside it, who can read the sink, whether it
is forwarded off-host — is an operator finding, not a repository fact
(`docs/OPERATIONS.md:3-10`). Do not write the stronger sentence into `docs/OPERATIONS.md` before
the questionnaire below is answered.

### Ask the operator first

The section cannot be written honestly before these are answered. Each has a discovery command
to run on the host:

| #   | Question                                                                     | How to find out                                                             |
| --- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| 1   | Is there a reverse proxy, and does it write an access log?                   | `nginx -T \| grep -E 'log_format\|access_log'`                              |
| 2   | Does gunicorn log access itself?                                             | inspect the systemd unit for `--access-logfile` / `--access-logformat`      |
| 3   | What does journald retain?                                                   | `systemctl show systemd-journald --property=Storage,MaxRetentionSec`        |
| 4   | Where does each log go, and for how long?                                    | `/etc/logrotate.d/*`, plus the sink's own settings                          |
| 5   | Is any log forwarded off the VPS — hosted logging, APM, CDN, load balancer?  | operator knowledge                                                          |
| 6   | Who can read or export them, and can records be searched or deleted by path? | operator knowledge                                                          |
| 7   | **Where does the app's own stderr go, and for how long is it kept?**         | `journalctl -u <unit>`; check the unit's `StandardOutput=`/`StandardError=` |
| 8   | **Does anything grep or forward those application logs?**                    | operator knowledge — this is the surface carrying `conv=<uuid>` at INFO     |

### Then write the section

Add it as a sibling `#` section after "Registrations pause" — that file's own instruction
(`docs/OPERATIONS.md:12-13`) is to add siblings rather than new files. Match the
registrations-pause voice: an H1, a bold `**Status:**` line with a date, then bold-lead
paragraphs. Do not import the email section's Problem / Root cause / Solution scaffold; only
that section uses it.

The section should carry: a findings table with **a row per layer for each of the two surfaces** —
HTTP access log (proxy, WSGI) and application log (stderr capture, forwarder) — recording for
each whether the identifier is retained, for how long, and who can read it; the acceptance
posture chosen; and the date and operator who verified it.

`docs/OPERATIONS.md:8-10` already names this as one of two things "not yet written up". Closing
this item means editing that paragraph too, in the same commit — CLAUDE.md's rule about a change
that makes a document wrong.

### If scrubbing turns out to be needed

It belongs in the proxy, not in Flask — the WSGI server and proxy log the request line before
and independently of any Flask hook, so a `before_request` cannot help.

The regex is UUID-shaped on purpose: a loose `~^/c/` would also rewrite any future `/c/`-prefixed
route, silently blinding the log to paths this task never meant to touch.

```nginx
map $request_uri $loggable_uri {
    ~^/c/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}  /c/:id;
    default $request_uri;
}

log_format scrubbed '$remote_addr - $remote_user [$time_local] '
                    '"$request_method $loggable_uri $server_protocol" '
                    '$status $body_bytes_sent "$http_referer" "$http_user_agent"';

access_log /var/log/nginx/access.log scrubbed;
```

Shortened retention is the cheaper control and needs no config change at all. Either way the
snippet is deployment configuration and does not enter this repository. Changing nginx does not
rewrite records already retained; those need the sink's own deletion procedure.

**And nginx does not touch the second surface.** The `conv=<uuid>` lines the application writes
to stderr are unaffected by any proxy log format. If those need scrubbing too, that is a
`logging.Filter` in `web/api/app.py` — an application change, and therefore a different task from
this one. Decide deliberately whether it is in scope; do not let a scrubbed access log create the
impression that the identifier is gone from the host.

---

## Rollout order

Four commits. **Only one ordering constraint is a genuine dependency; the rest is sequencing
preference, and the plan should not dress it up as more.**

- **A before B** is real, and only because of `ASSET_VERSION`: keeping the JS-touching commit
  alone makes the bump unambiguous. Combine them and the bump has to cover both.
- **C after A and B is not a code dependency.** The CSP and the signup spread have nothing to do
  with notification authorization. It matters only if C is run against an environment where A and
  B are _deployed_ — then C exercises what will actually ship. If the live run happens against a
  host that does not yet carry A and B, run it whenever the credentials appear and note which
  build it tested.
- **D last** is real in the weak sense that C's run is the natural moment to be inside the
  deployment already, with shell access, looking at logs.

**Closing each `TODO.md` entry is part of its commit, not a follow-up.** Per
[`docs/archive/README.md`](archive/README.md#adding-to-this-archive): add a dated closing note,
move the whole entry to `docs/archive/TODO-resolved.md`, and delete its line from the Open index
at the top of `TODO.md`. This applies to all four, including A and B.

### Commit A — CSP `img-src` and its first test

`web/api/app.py:1364` and new `web/tests/test_security_headers.py`. First because it is
self-contained, touches no JS, and needs no `ASSET_VERSION` bump — so it cannot collide with
Commit B. Close the `TODO.md` entry in this commit, and in the closing note record that the
`Referer` premise was wrong and the `DOMPurify` `<img>` path was the actual reason — a corrected
premise is worth more to the next reader than a tick. Also open the lordicon dead-config entry
here, so that discovery survives this plan's archival.

Gate: `python -m pytest -m "not browser and not integration"`, `ruff check . --fix && ruff format .`,
`mypy web`, then the twelve-cell matrix plus the two spot checks.

**On `mypy web`:** it currently fails in this dev environment on a pre-existing numpy/mypy stub
incompatibility that reproduces identically on clean `main`. That failure is not this commit's,
and it must not be treated as a red gate. Confirm the failure is the same one — diff it against
`main` — and proceed. It gates the `lint` CI job, so if CI is green there, that is the signal to
trust.

### Commit B — Signup spread order, JSDoc, browser test, `ASSET_VERSION`

`static/js/modules/services.js:384` and its JSDoc, the new test in
`web/tests/test_signup_identity_capture.py`, and the bump at `web/api/app.py:249`. Second because
it is the only commit here that touches JS; keeping it alone makes the bump unambiguous. Confirm
the test fails before the fix. Close the `TODO.md` entry in this commit too, by the same archive
procedure.

Gate: `python -m pytest -m browser --browser chromium`, `npm run lint:fix && npm run format`,
`pre-commit run --all-files`. `mypy web` carries the same pre-existing-failure caveat as Commit A
— `pre-commit` deliberately does not run it (see CLAUDE.md), so this gate is really the browser
suite plus the JS linters.

### Commit C — Notification-center live-auth verification

Blocked on credentials, not on A or B. Prefer running it against a host that already carries A
and B so the pass exercises what will ship — but if the credentials arrive first, run it and
record which build was tested. Documentation-only commit: plan `STATUS:`, a dated verification
section, and the `TODO.md` closure. Do not claim completion unless steps 6, 9, 11, 12 and 14 all
pass, each with the evidence named beside it.

Gate: the sixteen-step checklist against a live project; full suite still green.

### Commit D — `docs/OPERATIONS.md` access-log section

Last because it depends on operator answers this repository cannot produce, and because Commit
C's run is a natural moment to inspect the deployment's logging while already inside it. Edit
`docs/OPERATIONS.md:8-10` in the same commit and close the `TODO.md` entry.

Gate: `npm run lint:md && npm run format:md`; questionnaire answered, no placeholders left.

---

## Close-out

- Both non-browser and browser suites green, including the two new tests.
- Twelve-cell console sweep clean, plus `/privacy` and `/c/<uuid>` spot checks.
- Live checklist passed, with steps 6, 9, 11, 12 and 14 explicitly recorded.
- `docs/OPERATIONS.md` section merged and its `STATUS:` date refreshed; the lines 7-9 placeholder
  paragraph updated.
- All four `TODO.md` entries closed, moved through the archive procedure, and their index lines
  deleted.
- One new `TODO.md` entry opened for the dead lordicon CSP allowances.
- Any production-affecting lever used during Task 3 — a dashboard JWT-expiry change, an egress
  block — reverted, with the revert confirmed in the run record rather than assumed.

---

## How this plan was built, and what is still unverified

Three independent passes, then a review. A first-party audit of the tree; a security-research
pass (Gemini 3.7 Flash, high effort); an independent read-only implementation audit (GPT-5.6
Luna, xhigh); and an adversarial review of the resulting document (GPT-5.6 Terra, xhigh). Every
`file:line` above was re-opened by hand rather than taken from a report — that check caught real
errors in all three inputs, including a claim that a runtime signup test was impractical (it is
not) and an inventory that stopped at three log sites when there are about a dozen.

**Verified by reading source:** the CSP dict and debug branch; the complete image surface across
all five templates plus `static/js/` and `static/css/`; the Bootstrap CDN stylesheet's 23 `url(`
tokens; the sole `Services.signup` call site; the import map and the context-level CDN mock that
make the proposed browser test resolvable; the SDK's `_handleTokenChanged` wiring; the deep-link
route and its contract tests; every conversation-id logging site; the absence of any deployment
logging configuration.

**Not verified here, and flagged rather than assumed:** anything requiring live Supabase
credentials (Task 3 in full) or access to the production host (Task 4's answers). The
`node_modules` SDK read is a strong prior, not the artefact the browser executes. The captured
Talisman header serialization is current behaviour of an unpinned dependency
(`requirements.txt:4`), not a frozen contract.
