"""CSP `img-src` must admit only same-origin and `data:` sources.

Model output renders through a DOMPurify profile that permits `<img>`
(static/js/modules/stream-render.js:24), so a markdown image in an answer was
a live outbound beacon under the previous `'self' data: https:` policy. See
docs/security-hardening-plan.md Task 1.
"""

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
    font-src and connect-src only, deliberately. Equality, not just an absence
    check for `https:` — so a future debug relaxation adding `blob:` or `http:`
    to img-src fails this test too, rather than sliding past it."""
    client = create_app(testing=True).test_client()

    directives = _directives(client.get("/"))

    assert directives["img-src"] == "'self' data:"
