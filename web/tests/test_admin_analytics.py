"""The two read-only analytics routes, and the privacy rules they carry.

Everything here runs against the REAL in-memory chat backend — turns are
seeded through `append_turn`, the same call the chat route makes — so the
aggregate is computed over production-shaped rows rather than over a fixture
list invented for the assertion.

The one thing these tests cannot prove is that the Python double and the
Postgres function agree, because only one of the two is running.
`test_the_double_and_the_database_normalise_alike` narrows that to the part
that actually differs between the engines: `NORMALISATION_FIXTURE` below. It
is NOT shared with `supabase/tests/rpc_behaviour.test.sql` — that file cannot
read Python, seeds its own eight phrasings, and proves grouping rather than the
key. What ties the two engines together is a check run by hand against the live
function (the fixture, then 52 space / control / format code points one by one;
see the plan's build record). Both have caught a real divergence; neither is
automatic, so after touching either bracket expression, run it again.
"""

from __future__ import annotations

import itertools
import re

import pytest

from web.api.app import create_app
from web.services.admin_store import normalize_question

ADMIN = {"Authorization": "Bearer fake_admin_token"}
READER = {"Authorization": "Bearer fake_token"}

QUESTIONS = "/admin/api/analytics/questions"
CITATIONS = "/admin/api/analytics/citations"

# Any of these appearing as a response key would be identity leaking out of a
# surface whose whole premise is that it carries none. Same expression the new
# `function_acls.test.sql` check runs against `pg_get_function_result`.
IDENTIFIER_KEY_RE = re.compile("owner|user_id|actor|email|session_id|message_id")


# ── the normalisation contract ────────────────────────────────────────────────
#
# (raw, expected) pairs, written with `\u` escapes so the file survives every
# editor and every terminal. SHARED FIXTURE: the same list is pasted into
# `supabase/tests/rpc_behaviour.test.sql`, which runs it against the real
# function. Add a pair here and it must be added there in the same commit.
NORMALISATION_FIXTURE = [
    # case
    ("Renew The Licence", "renew the licence"),
    # doubled and tripled spaces
    ("renew  the   licence", "renew the licence"),
    # tab and newline
    ("renew\tthe\nlicence", "renew the licence"),
    # the rest of the ASCII six Postgres's own `\s` covers
    ("renew\r\nthe\x0clicence\x0b", "renew the licence"),
    # U+00A0 NO-BREAK SPACE — the character Postgres's `\s` does NOT match
    ("renew\u00a0the licence", "renew the licence"),
    # U+3000 IDEOGRAPHIC SPACE
    ("renew\u3000the licence", "renew the licence"),
    # U+200B ZERO WIDTH SPACE — deleted, never turned into a space
    ("renew \u200bthe licence", "renew the licence"),
    # U+200F RIGHT-TO-LEFT MARK
    ("\u200frenew the licence", "renew the licence"),
    # U+2066 LEFT-TO-RIGHT ISOLATE and U+2069 POP DIRECTIONAL ISOLATE
    ("renew \u2066the\u2069 licence", "renew the licence"),
    # U+FEFF ZERO WIDTH NO-BREAK SPACE, the byte-order mark a paste carries
    ("\ufeffrenew the licence", "renew the licence"),
    # one trailing stop, each kind
    ("renew the licence?", "renew the licence"),
    ("renew the licence\u061f", "renew the licence"),  # U+061F Arabic question mark
    ("renew the licence!", "renew the licence"),
    ("renew the licence.", "renew the licence"),
    ("renew the licence\u06d4", "renew the licence"),  # U+06D4 Arabic full stop
    ("renew the licence\u2026", "renew the licence"),  # U+2026 horizontal ellipsis
    # a trailing RUN, punctuation and spaces together
    ("renew the licence?! ", "renew the licence"),
    # internal punctuation is kept — only a TRAILING run is stripped
    ("Renew the licence? Or not?", "renew the licence? or not"),
    # an Arabic sentence: no case to fold, an NBSP inside it, a trailing U+061F
    (
        "\u0645\u0627\u00a0\u0647\u064a \u0645\u062a\u0637\u0644\u0628\u0627\u062a \u0627\u0644\u062a\u0633\u062c\u064a\u0644\u061f",
        "\u0645\u0627 \u0647\u064a \u0645\u062a\u0637\u0644\u0628\u0627\u062a \u0627\u0644\u062a\u0633\u062c\u064a\u0644",
    ),
    # Found by a third review and confirmed against the live expression over 52
    # code points: Postgres's `\\s` matches U+2028 and U+2029 (a PDF's soft line
    # break) and this side did not...
    ("renew the\u2028licence", "renew the licence"),
    ("renew the\u2029licence", "renew the licence"),
    # ...and `btrim` strips U+0020 only, where a bare `.strip()` also ate these.
    # They SURVIVE, in both engines, and so block the trailing-stop pass too.
    ("renew the licence.\u0085", "renew the licence.\u0085"),
    ("\x1crenew the licence", "\x1crenew the licence"),
    ("renew the licence\x1f", "renew the licence\x1f"),
    # THE NEGATIVE PAIR: two different questions that must NOT collide.
    ("Does the licence require X?", "does the licence require x"),
    ("The licence requires X.", "the licence requires x"),
]


# ── fixtures and seeding ──────────────────────────────────────────────────────


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def chat(app):
    return app.config["_testing_chat_backend"]


_ids = itertools.count(1)


def _sources(cited: int, retrieved: int) -> list[dict]:
    """`retrieved` passages, the first `cited` of them marked cited."""
    total = max(cited, retrieved)
    return [
        {
            "source_index": index,
            "document": "guideline.pdf",
            "category": "regulatory",
            "snippet": "a passage",
            "cited": index <= cited,
        }
        for index in range(1, total + 1)
    ]


def ask(chat, owner, question, *, lang="en", category="all", cited=0, retrieved=0, session=None):
    """Save one turn the way the chat route saves one. Returns its session id."""
    session_id = session or f"session-{next(_ids)}"
    chat.append_turn(
        owner_id=owner,
        session_id=session_id,
        client_request_id=f"request-{next(_ids)}",
        question=question,
        answer="An answer.",
        sources=_sources(cited, retrieved),
        lang=lang,
        category=category,
        model="test-model",
        corpus_revision="rev-1",
        owner_key=None,
        session_key=None,
        archive_opted_out=True,
    )
    return session_id


def questions_of(client, query=""):
    return client.get(f"{QUESTIONS}{query}", headers=ADMIN).get_json()["questions"]


def stats_of(client, query=""):
    return client.get(f"{CITATIONS}{query}", headers=ADMIN).get_json()["stats"]


def faq_text(app, lang="en"):
    """One real sidebar question, taken from the loaded catalogue.

    Read rather than hardcoded: the flag is only meaningful if it matches what
    `faq.yaml` actually ships, and a copy here would go stale on the next edit.
    """
    categories = app.config["FREQUENT_QUESTIONS"][lang]
    return categories["regulatory"]["questions"][0]["text"]


# ── the gates ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", [QUESTIONS, CITATIONS])
def test_every_analytics_route_refuses_an_unauthenticated_caller(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", [QUESTIONS, CITATIONS])
def test_every_analytics_route_refuses_a_reader(client, path):
    assert client.get(path, headers=READER).status_code == 403


# ── grouping, the floor and the bucket ────────────────────────────────────────


def test_questions_are_grouped_by_normalized_text(client, chat):
    ask(chat, "owner-a", "What Are  The Requirements?")
    ask(chat, "owner-b", "what are\u00a0the requirements")

    rows = questions_of(client)

    assert len(rows) == 1
    assert rows[0]["asks"] == 2
    # The most recent RAW phrasing, not the normalised key.
    assert rows[0]["question"] == "what are\u00a0the requirements"


def test_a_question_only_one_account_asked_is_not_returned(client, chat):
    ask(chat, "owner-solo", "A question only one account ever asks")
    ask(chat, "owner-solo", "A question only one account ever asks")
    ask(chat, "owner-solo", "A question only one account ever asks")

    assert questions_of(client) == []


def test_the_asker_floor_cannot_be_lowered_through_the_route(client, chat):
    ask(chat, "owner-solo", "A question only one account ever asks")

    assert questions_of(client, "?min_askers=1") == []
    assert questions_of(client, "?min_askers=0") == []


def test_the_asker_count_is_null_below_five_and_exact_from_five(client, chat):
    for index in range(4):
        ask(chat, f"owner-{index}", "Asked by four accounts")
    for index in range(5):
        ask(chat, f"owner-{index}", "Asked by five accounts")

    by_question = {row["question"]: row["askers"] for row in questions_of(client)}

    assert by_question["Asked by four accounts"] is None
    assert by_question["Asked by five accounts"] == 5


def test_a_sidebar_question_is_flagged_and_a_typed_one_is_not(client, app, chat):
    english = faq_text(app)
    arabic = faq_text(app, "ar")
    # The FAQ's own text, mangled the way a paste mangles it: different case,
    # a no-break space and a trailing question mark.
    ask(chat, "owner-a", english.upper().replace(" ", "\u00a0", 1))
    ask(chat, "owner-b", f"{english} ")
    ask(chat, "owner-a", f"{arabic}؟", lang="ar")
    ask(chat, "owner-b", arabic, lang="ar")
    ask(chat, "owner-a", "Something nobody put in the sidebar")
    ask(chat, "owner-b", "Something nobody put in the sidebar")

    flags = {row["question"]: row["from_faq"] for row in questions_of(client)}

    assert flags[f"{english} "] is True
    assert flags[arabic] is True
    assert flags["Something nobody put in the sidebar"] is False


@pytest.mark.parametrize(("raw", "expected"), NORMALISATION_FIXTURE)
def test_the_double_and_the_database_normalise_alike(raw, expected):
    assert normalize_question(raw) == expected


def test_the_normalisation_fixture_carries_a_pair_that_must_not_collide():
    """Every other pair proves a merge. This one proves the merges stop.

    A normaliser that returned `""` would satisfy all of the above.
    """
    keys = {normalize_question(raw) for raw, _ in NORMALISATION_FIXTURE}

    assert normalize_question("Does the licence require X?") != normalize_question(
        "The licence requires X."
    )
    assert len(keys) > 1


# ── the two failures citation stats keep apart ────────────────────────────────


def test_a_turn_with_no_retrieval_is_separated_from_one_that_cited_nothing(client, chat):
    ask(chat, "owner-a", "Search found passages and none were cited", retrieved=3, cited=0)
    ask(chat, "owner-b", "Search found nothing at all", retrieved=0)

    total = next(row for row in stats_of(client) if row["scope"] == "total")

    assert total["turns"] == 2
    assert total["turns_uncited"] == 1
    assert total["turns_no_retrieval"] == 1
    assert total["retrieved_total"] == 3
    assert total["cited_total"] == 0


def test_citation_stats_break_down_by_lang_and_category(client, chat):
    ask(chat, "owner-a", "An English question", lang="en", category="all", retrieved=2, cited=1)
    ask(chat, "owner-b", "Another English one", lang="en", category="regulatory", retrieved=1)
    ask(chat, "owner-c", "An Arabic question", lang="ar", category="regulatory", retrieved=1)

    rows = stats_of(client)
    scopes = {row["scope"] for row in rows}
    buckets = {(row["scope"], row["bucket"]): row["turns"] for row in rows}

    assert scopes == {"total", "lang", "category"}
    assert buckets[("total", None)] == 3
    assert buckets[("lang", "en")] == 2
    assert buckets[("lang", "ar")] == 1
    assert buckets[("category", "all")] == 1
    assert buckets[("category", "regulatory")] == 2


@pytest.mark.parametrize(
    ("query", "kept", "dropped", "turns"),
    [
        ("?lang=en", "An English question", "An Arabic question", 2),
        ("?lang=ar", "An Arabic question", "An English question", 4),
        ("?category=regulatory", "A regulatory question", "An English question", 2),
        ("?category=all", "An English question", "A regulatory question", 4),
    ],
)
def test_a_filter_narrows_both_routes(client, chat, query, kept, dropped, turns):
    """The filters are read off the ASSISTANT row, the only one that carries
    them, and they narrow the aggregate rather than merely the breakdown."""
    for owner in ("owner-a", "owner-b"):
        ask(chat, owner, "An English question", lang="en", category="all")
        ask(chat, owner, "An Arabic question", lang="ar", category="all")
        ask(chat, owner, "A regulatory question", lang="ar", category="regulatory")

    listed = [row["question"] for row in questions_of(client, query)]

    assert kept in listed
    assert dropped not in listed
    assert next(row for row in stats_of(client, query) if row["scope"] == "total")["turns"] == turns


def test_an_empty_string_filter_is_no_filter(client, chat):
    """The console sends `lang=` for "both languages"."""
    for owner in ("owner-a", "owner-b"):
        ask(chat, owner, "An English question", lang="en")
        ask(chat, owner, "An Arabic question", lang="ar")

    assert len(questions_of(client, "?lang=&category=")) == 2


def test_an_empty_window_is_an_empty_list_on_both_routes(client):
    assert questions_of(client) == []
    assert stats_of(client) == []


def test_deleting_a_conversation_removes_it_from_the_aggregate(client, chat):
    """Retroactivity is the deletion promise working, not a bug to fix later."""
    session = ask(chat, "owner-a", "A question two accounts asked")
    ask(chat, "owner-b", "A question two accounts asked")
    assert questions_of(client)[0]["asks"] == 2

    chat.delete_session("owner-a", session)

    assert questions_of(client) == []
    assert next(row for row in stats_of(client) if row["scope"] == "total")["turns"] == 1


# ── nothing that identifies anybody ───────────────────────────────────────────


def test_the_analytics_responses_carry_the_shape_the_identity_test_searches(client, chat):
    """Paired with the test below so that one cannot pass on an empty body."""
    ask(chat, "owner-alpha-7e1c", "A question two accounts asked", retrieved=2, cited=1)
    ask(chat, "owner-beta-3d92", "A question two accounts asked", retrieved=1)

    row = questions_of(client)[0]
    total = next(item for item in stats_of(client) if item["scope"] == "total")

    assert set(row) == {"question", "asks", "uncited", "askers", "from_faq"}
    assert row["question"] == "A question two accounts asked"
    assert row["asks"] == 2
    assert total["turns"] == 2


def test_no_identity_appears_in_any_analytics_response(client, chat):
    ask(chat, "owner-alpha-7e1c", "A question two accounts asked", retrieved=2, cited=1)
    ask(chat, "owner-beta-3d92", "A question two accounts asked", retrieved=1)

    for path in (QUESTIONS, CITATIONS):
        response = client.get(path, headers=ADMIN)
        body = response.get_data(as_text=True)

        assert "owner-alpha-7e1c" not in body
        assert "owner-beta-3d92" not in body
        assert "example.com" not in body
        for rows in response.get_json().values():
            for row in rows:
                leaked = [key for key in row if IDENTIFIER_KEY_RE.search(key)]
                assert not leaked, f"{path} carries {leaked}"


# ── the parameters ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", [QUESTIONS, CITATIONS])
def test_an_unknown_lang_is_422(client, path):
    response = client.get(f"{path}?lang=fr", headers=ADMIN)

    assert response.status_code == 422
    assert response.get_json()["error"] == "invalid_lang"


@pytest.mark.parametrize("path", [QUESTIONS, CITATIONS])
def test_an_unknown_category_is_422(client, path):
    response = client.get(f"{path}?category=cosmetics", headers=ADMIN)

    assert response.status_code == 422
    assert response.get_json()["error"] == "invalid_category"


def test_an_unknown_order_is_422(client):
    response = client.get(f"{QUESTIONS}?order=askers", headers=ADMIN)

    assert response.status_code == 422
    assert response.get_json()["error"] == "invalid_order"


# past int4 Postgres refuses the argument itself: a 400 here, not a 500 there
_BAD_DAYS = ["?days=soon", "?days=0", "?days=-30", "?days=2147483648"]
_BAD_LIMIT = ["?limit=none", "?limit=0", "?limit=2147483648"]


@pytest.mark.parametrize(
    "url",
    [QUESTIONS + query for query in _BAD_DAYS + _BAD_LIMIT]
    + [CITATIONS + query for query in _BAD_DAYS],
)
def test_an_unparseable_window_is_400(client, url):
    response = client.get(url, headers=ADMIN)

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_window"


@pytest.mark.parametrize("query", _BAD_LIMIT)
def test_the_citations_route_does_not_refuse_an_argument_it_never_reads(client, query):
    """It takes no `limit`, so a bad one is not its business."""
    assert client.get(CITATIONS + query, headers=ADMIN).status_code == 200


def _age_session(chat, session_id, days):
    """Backdate one saved conversation. `append_turn` owns `created_at` and
    offers no override — as `chat_append_turn` does, which is why the SQL test
    backdates with a direct UPDATE too."""
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone

    then = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with chat._lock:
        chat._messages[session_id] = [
            replace(message, created_at=then) for message in chat._messages[session_id]
        ]


@pytest.mark.parametrize("path", [QUESTIONS, CITATIONS])
def test_a_window_narrower_than_seven_days_is_widened_to_seven(client, chat, path):
    """The floor is a privacy control: a one-day window would let a caller
    difference today against yesterday down to a single turn. A turn three
    days old must still be counted at `days=1`, and one eight days old must
    not — so this fails if the floor is removed AND if the window stops
    bounding at all."""
    ask(chat, "owner-a", "Renew the licence")
    _age_session(chat, ask(chat, "owner-b", "renew the licence"), days=3)
    _age_session(chat, ask(chat, "owner-c", "renew the licence"), days=8)

    payload = client.get(f"{path}?days=1", headers=ADMIN).get_json()

    if path == QUESTIONS:
        assert [row["asks"] for row in payload["questions"]] == [2]
    else:
        assert next(r for r in payload["stats"] if r["scope"] == "total")["turns"] == 2


@pytest.mark.parametrize("path", [QUESTIONS, CITATIONS])
def test_an_out_of_range_window_is_clamped_rather_than_refused(client, path):
    """The clamp is the database's, written once. The route only refuses what
    is not a window at all."""
    assert client.get(f"{path}?days=1&limit=99999", headers=ADMIN).status_code == 200


def test_the_ordering_can_be_switched_to_the_uncited_count(client, chat):
    for owner in ("owner-a", "owner-b"):
        ask(chat, owner, "Asked more often", retrieved=2, cited=2)
        ask(chat, owner, "Answered without a citation", retrieved=2, cited=0)
    ask(chat, "owner-a", "Asked more often", retrieved=2, cited=2)

    assert questions_of(client)[0]["question"] == "Asked more often"
    assert questions_of(client, "?order=uncited")[0]["question"] == "Answered without a citation"


@pytest.mark.parametrize("path", [QUESTIONS, CITATIONS])
def test_no_storage_is_503(app, client, path):
    app.config["admin_backend"] = lambda: None

    response = client.get(path, headers=ADMIN)

    assert response.status_code == 503
    assert response.get_json()["error"] == "storage_unavailable"


def test_a_malformed_faq_catalogue_cannot_take_the_questions_route_down(app, client, chat):
    """`faq.yaml` is hand-edited. `/api/frequent-questions` already skips a
    block that is not a mapping; this traversal reads the same file and has to
    be at least as forgiving — a typo in the sidebar must not 500 the console.
    """
    app.config["FREQUENT_QUESTIONS"] = {
        "en": {"regulatory": "oops", "biological": {"questions": ["bare", {"text": "Real one?"}]}},
        "ar": None,
    }
    ask(chat, "owner-a", "real one")
    ask(chat, "owner-b", "Real one?")

    response = client.get(QUESTIONS, headers=ADMIN)

    assert response.status_code == 200
    assert [row["from_faq"] for row in response.get_json()["questions"]] == [True]


def test_a_faq_entry_whose_text_is_not_a_string_is_skipped(app, client, chat):
    """`yaml.safe_load` reads an unquoted `text: 2026` as an int and `text: yes`
    as a bool. Both are truthy, so a truthiness guard lets them through to a
    regex that raises."""
    app.config["FREQUENT_QUESTIONS"] = {
        "en": {"regulatory": {"questions": [{"text": 2026}, {"text": True}, {"text": "Real one?"}]}}
    }
    ask(chat, "owner-a", "real one")
    ask(chat, "owner-b", "Real one?")

    response = client.get(QUESTIONS, headers=ADMIN)

    assert response.status_code == 200
    assert [row["from_faq"] for row in response.get_json()["questions"]] == [True]


@pytest.mark.parametrize("path", [QUESTIONS, CITATIONS])
def test_an_empty_window_argument_is_the_default_like_an_empty_filter(client, path):
    """`?lang=` means no filter; `?days=` answering 400 was the odd one out."""
    assert client.get(f"{path}?days=&lang=", headers=ADMIN).status_code == 200


def test_a_row_with_no_partner_is_dropped_not_mispaired(client, chat):
    """The SQL pairs a turn's rows by request id, so a stray row is dropped by
    the join. Pairing by list position instead would, from that row on, read
    every ANSWER as the next question."""
    from dataclasses import replace

    session = ask(chat, "owner-a", "Renew the licence")
    ask(chat, "owner-b", "renew the licence")
    with chat._lock:
        rows = chat._messages[session]
        chat._messages[session] = [replace(rows[1], content="a stray notice"), *rows]

    questions = client.get(QUESTIONS, headers=ADMIN).get_json()["questions"]

    assert [(row["question"], row["asks"]) for row in questions] == [("renew the licence", 2)]


def test_tied_groups_come_back_in_code_point_order(client, chat):
    """On a small population most groups tie at two asks, so the tie-break
    decides which rows survive `limit`. The SQL breaks ties `collate "C"`;
    these are the four keys `rpc_behaviour.test.sql` uses, chosen because the
    database's own collation orders them differently."""
    for owner in ("owner-a", "owner-b"):
        for question in ("tie-b", "tie a", "tiea", "tie b"):
            ask(chat, owner, question)

    questions = client.get(QUESTIONS, headers=ADMIN).get_json()["questions"]

    assert [row["question"] for row in questions] == ["tie a", "tie b", "tie-b", "tiea"]
