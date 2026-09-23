"""CSP `img-src` must admit only same-origin and `data:` sources.

Model output renders through a DOMPurify profile that permits `<img>`
(static/js/modules/stream-render.js:24), so a markdown image in an answer was
a live outbound beacon under the previous `'self' data: https:` policy. See
docs/archive/2026-09-23_security-hardening.md Task 1.
"""

from web.api.app import create_app, realtime_ws_origins


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
    font-src and connect-src only, deliberately. Equality, not just an absence
    check for `https:` — so a future debug relaxation adding `blob:` or `http:`
    to img-src fails this test too, rather than sliding past it."""
    client = create_app(testing=True).test_client()

    directives = _directives(client.get("/"))

    assert directives["img-src"] == "'self' data:"


def test_no_directive_admits_the_retired_icon_cdn(monkeypatch):
    """`cdn.lordicon.com` sat in script-src and connect-src with no `lord-icon`
    element or reference anywhere in the tree. A script origin nobody uses is
    attack surface nobody watches; removed 2026-09-23. The non-testing app
    needs a key to boot, which CI has no `.env` to supply."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for testing in (True, False):
        policy = (
            create_app(testing=testing).test_client().get("/").headers["Content-Security-Policy"]
        )
        assert "lordicon" not in policy


def test_the_realtime_origin_comes_from_the_url_the_browser_uses():
    """P9 of docs/supabase-key-incident-fix-plan.md.

    `wss://*.supabase.co` used to be appended unconditionally, right after the
    project's own origin — so the specific entry narrowed nothing and setting
    `SUPABASE_PROJECT_REF` looked like hardening while achieving exactly nothing.

    The origin is derived from SUPABASE_URL because that is what `services.js`
    hands to `createClient`, and therefore the host Realtime opens its socket
    against. Tested through the helper rather than a response header because
    `testing=True` takes the debug branch, which replaces `connect-src` wholesale.
    """
    origins = realtime_ws_origins("https://abcdefghijklmnopqrst.supabase.co")

    assert origins == ["wss://abcdefghijklmnopqrst.supabase.co"]
    assert "wss://*.supabase.co" not in origins


def test_a_stale_project_ref_cannot_block_the_real_socket():
    """The regression the first version of this shipped: CSP built from
    SUPABASE_PROJECT_REF while the socket is built from SUPABASE_URL. A ref left
    over from another project — the same copy-paste behind the incident — would
    have blocked Realtime to the correct host while REST kept working, so the app
    degraded to poll-only with nothing raised anywhere."""
    origins = realtime_ws_origins("https://correct.supabase.co", "staleoldproject")

    assert origins == ["wss://correct.supabase.co"]


def test_a_junk_project_ref_falls_back_rather_than_building_a_broken_policy():
    """Two values that must never be interpolated on trust. `*` rebuilds the very
    wildcard this narrowing removed while reading as though it were locked down;
    a space yields `wss:// .supabase.co`, which blocks Realtime outright. Both
    are rejected and fall back to the honest wildcard."""
    for junk in ("*", " ", "has space", "semi;colon", "UPPER_CASE!"):
        assert realtime_ws_origins(None, junk) == ["wss://*.supabase.co"], junk


def test_the_ref_is_still_honoured_when_there_is_no_url():
    """It remains a usable fallback, just a validated one."""
    assert realtime_ws_origins(None, "abcdefghijklmnopqrst") == [
        "wss://abcdefghijklmnopqrst.supabase.co"
    ]


def test_without_a_url_or_ref_the_wildcard_remains_so_realtime_still_works():
    """The wildcard is the FALLBACK, not a companion. A deployment configuring
    neither must keep working exactly as before rather than losing Realtime to a
    tightening it never opted into."""
    assert realtime_ws_origins(None, None) == ["wss://*.supabase.co"]
    assert realtime_ws_origins("", "") == ["wss://*.supabase.co"]
