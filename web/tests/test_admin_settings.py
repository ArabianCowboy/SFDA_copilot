"""Runtime settings: overrides, validation, and what reverting means.

Nothing here applies a setting to generation — that is the next phase. What is
pinned is the layer underneath: that the store holds only what an operator
changed, that a patch is validated against the *resulting* state rather than in
isolation, and that a refusal says which field and by how much.
"""

from __future__ import annotations

import pytest

from web.api.app import create_app
from web.services.admin_store import InMemoryAdminBackend
from web.services.audit import AuditActor
from web.services.settings_service import (
    SettingsService,
    deployed_defaults,
)

ADMIN = {"Authorization": "Bearer fake_admin_token"}

# Settings writes now carry who made them, because the change and its audit
# row are written together — there is no way to store one without the other.
ACTOR = AuditActor("admin-id", "admin@example.com", "127.0.0.1", "pytest")
AUTH = {"Authorization": "Bearer fake_token"}


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def service():
    backend = InMemoryAdminBackend()
    return SettingsService(lambda: backend)


# ── Overrides, not a copy ─────────────────────────────────────────────────────


def test_an_untouched_instance_stores_nothing(service):
    """The absence of a row is the deployed default, not an empty config."""
    assert service.overrides() == {}
    assert service.snapshot() == deployed_defaults()


def test_only_what_changed_is_stored(service):
    service.update({"model": "gpt-4o"}, actor=ACTOR)

    assert service.overrides() == {"model": "gpt-4o"}
    assert service.snapshot()["model"] == "gpt-4o"
    # Untouched keys still come from config.yaml, so a deploy that changes one
    # is picked up rather than shadowed by a row written months earlier.
    assert service.snapshot()["temperature"] == deployed_defaults()["temperature"]


def test_setting_a_key_to_null_reverts_it(service):
    """Distinct from writing the default's current value, which would pin it."""
    service.update({"model": "gpt-4o"}, actor=ACTOR)
    service.update({"model": None}, actor=ACTOR)

    assert service.overrides() == {}
    assert service.snapshot()["model"] == deployed_defaults()["model"]


def test_a_write_is_visible_immediately(service):
    """An operator must never see their own change lag behind the TTL."""
    service.update({"temperature": 0.7}, actor=ACTOR)
    assert service.snapshot()["temperature"] == 0.7


# ── Validation ────────────────────────────────────────────────────────────────


def test_a_model_outside_the_allowlist_is_refused(service):
    errors = service.update({"model": "gpt-does-not-exist"}, actor=ACTOR)
    assert [e.code for e in errors] == ["not_allowed"]
    assert service.overrides() == {}, "a refused patch must not be partly applied"


def test_an_unknown_setting_is_refused_rather_than_ignored(service):
    """Silently dropping it would tell an operator who mistyped a key that
    their change was saved."""
    errors = service.update({"tempreature": 0.5}, actor=ACTOR)
    assert [e.code for e in errors] == ["unknown_setting"]


def test_max_tokens_above_the_model_ceiling_is_refused_with_the_ceiling(service):
    """422 carrying the number, never a silent clamp.

    An operator corrected behind their back stops trusting the control.
    """
    errors = service.update({"max_tokens": 999_999}, actor=ACTOR)
    assert len(errors) == 1
    assert errors[0].code == "above_ceiling"
    assert errors[0].limit == 16384


def test_switching_model_is_validated_against_the_resulting_state(service):
    """The case that only a merged validation catches.

    Both values are individually fine; together they are not. Validating the
    patch alone would accept it and every request afterwards would 400 at the
    provider.
    """
    from web.services import settings_service

    # A model whose ceiling is below the currently-stored max_tokens.
    original = settings_service.allowed_models
    settings_service.allowed_models = lambda: [
        {"id": "gpt-4o-mini", "label": "mini", "max_output_tokens": 16384},
        {"id": "tiny-model", "label": "tiny", "max_output_tokens": 1024},
    ]
    try:
        service.update({"max_tokens": 16384}, actor=ACTOR)
        errors = service.update({"model": "tiny-model"}, actor=ACTOR)
    finally:
        settings_service.allowed_models = original

    assert [e.code for e in errors] == ["above_ceiling"]
    assert errors[0].limit == 1024


def test_passages_cannot_exceed_the_retriever(service):
    """Not a taste limit: retrieved[i] must be the same passage as prompt block
    [i], and the retriever cannot return more than k."""
    errors = service.update({"max_context_results": 500}, actor=ACTOR)
    assert [e.code for e in errors] == ["above_ceiling"]


@pytest.mark.parametrize("value", [-0.5, 2.5])
def test_temperature_outside_its_range_is_refused(service, value):
    errors = service.update({"temperature": value}, actor=ACTOR)
    assert [e.code for e in errors] == ["out_of_range"]


def test_a_boolean_is_not_a_number(service):
    """bool is an int in Python, so `max_tokens: true` would otherwise pass a
    naive isinstance check and reach the provider as 1."""
    errors = service.update({"max_tokens": True}, actor=ACTOR)
    assert [e.code for e in errors] == ["not_a_positive_integer"]


# ── Reading a store that has gone bad ────────────────────────────────────────


def test_invalid_stored_settings_fall_back_to_the_deployed_defaults():
    """The row is JSONB with no schema, so something could write nonsense into
    it directly. Serving that to the model would be worse than ignoring it."""
    backend = InMemoryAdminBackend({"model": "removed-from-the-allowlist"})
    service = SettingsService(lambda: backend)

    assert service.snapshot() == deployed_defaults()


def test_a_read_failure_serves_the_deployed_defaults():
    """A settings outage costs an operator their overrides, not every reader
    their answer."""

    class Broken:
        def get_settings(self):
            raise RuntimeError("supabase is down")

    assert SettingsService(lambda: Broken()).snapshot() == deployed_defaults()


def test_a_failed_read_during_an_update_does_not_delete_the_other_overrides():
    """The data-loss bug: a lenient read reused on the write path.

    `update()` replaces the whole document. If a failed read is flattened to
    `{}` there, saving one key during a transient outage writes `{}` plus that
    key — silently deleting every other override the operator had set.
    """
    backend = InMemoryAdminBackend({"model": "gpt-4o", "temperature": 0.7})

    reads = {"n": 0}
    real_get = backend.get_settings

    def flaky():
        reads["n"] += 1
        if reads["n"] > 1:  # the read inside update()
            raise RuntimeError("supabase blipped")
        return real_get()

    service = SettingsService(lambda: backend)
    service.snapshot()  # first read succeeds and warms the cache
    backend.get_settings = flaky
    reads["n"] = 1

    errors = service.update({"max_tokens": 8192}, actor=ACTOR)

    assert [e.code for e in errors] == ["storage_unavailable"]
    assert backend._settings == {"model": "gpt-4o", "temperature": 0.7}, (
        "a refused write must leave the stored overrides untouched"
    )


def test_an_unknown_key_set_to_null_is_still_refused(service):
    """Splitting removals out before the unknown-key check let
    `{"nonsense": null}` through as a removal of something that was never a
    setting — and reported it as saved."""
    errors = service.update({"nonsense": None}, actor=ACTOR)
    assert [e.code for e in errors] == ["unknown_setting"]


def test_an_absurd_number_is_a_422_rather_than_a_crash(client):
    """JSON has no integer limit, and float() on a few thousand digits raises
    OverflowError — which reached the client as a 500."""
    response = client.put(
        "/admin/api/settings", json={"temperature": int("9" * 4000)}, headers=ADMIN
    )
    assert response.status_code == 422
    assert response.get_json()["errors"][0]["field"] == "temperature"


def test_a_removal_is_validated_against_the_default_that_replaces_it(service):
    """Reverting restores the deployed default, which is not the value that was
    there before — so the resulting state is what must be checked."""
    from web.services import settings_service

    original = settings_service.allowed_models
    settings_service.allowed_models = lambda: [
        {"id": "gpt-4o-mini", "label": "mini", "max_output_tokens": 16384},
        {"id": "tiny", "label": "tiny", "max_output_tokens": 512},
    ]
    try:
        # Legal together: a small model with a small ceiling.
        assert service.update({"model": "tiny", "max_tokens": 512}, actor=ACTOR) == []
        # Removing max_tokens reverts it to the deployed 16384, which the tiny
        # model cannot accept. Validating the patch alone would miss this.
        errors = service.update({"max_tokens": None}, actor=ACTOR)
    finally:
        settings_service.allowed_models = original

    assert [e.code for e in errors] == ["above_ceiling"]


def test_a_write_with_no_storage_is_refused_rather_than_reported_as_saved():
    """Reporting success for a write that went nowhere is worse than the outage
    it is reporting."""
    service = SettingsService(lambda: None)
    errors = service.update({"model": "gpt-4o"}, actor=ACTOR)
    assert [e.code for e in errors] == ["storage_unavailable"]


# ── The API ───────────────────────────────────────────────────────────────────


def test_settings_are_readable_by_an_administrator(client):
    body = client.get("/admin/api/settings", headers=ADMIN).get_json()

    assert body["settings"]["model"] == deployed_defaults()["model"]
    assert body["overrides"] == {}

    # The console renders exactly this list and the server refuses anything
    # outside it, so the two cannot disagree. Asserted by shape rather than by
    # a literal list: enabling a model is a config decision, and a test that
    # names them turns every such decision into a test edit for no safety.
    models = body["allowed_models"]
    assert models, "the console needs at least one selectable model"
    assert deployed_defaults()["model"] in {m["id"] for m in models}, (
        "the deployed default must itself be selectable, or the console cannot "
        "show what is currently running"
    )
    for entry in models:
        assert entry["id"] and entry["label"]
        assert isinstance(entry["max_output_tokens"], int), (
            f"{entry['id']} has no verified output ceiling; the ceiling is the "
            f"only thing standing between a wrong value and a 400 per request"
        )


def test_settings_are_not_readable_by_a_reader(client):
    assert client.get("/admin/api/settings", headers=AUTH).status_code == 403
    assert client.put("/admin/api/settings", json={}, headers=AUTH).status_code == 403


def test_settings_require_a_bearer_header(client):
    assert client.get("/admin/api/settings").status_code == 401


def test_a_valid_patch_returns_the_new_state(client):
    response = client.put("/admin/api/settings", json={"model": "gpt-4o"}, headers=ADMIN)

    assert response.status_code == 200
    body = response.get_json()
    assert body["settings"]["model"] == "gpt-4o"
    assert body["overrides"] == {"model": "gpt-4o"}


def test_a_rejected_patch_is_a_422_with_per_field_codes(client):
    response = client.put("/admin/api/settings", json={"max_tokens": 999_999}, headers=ADMIN)

    assert response.status_code == 422
    body = response.get_json()
    assert body["error"] == "validation_failed"
    assert body["errors"] == [{"field": "max_tokens", "code": "above_ceiling", "limit": 16384}]


def test_a_non_object_payload_is_rejected(client):
    response = client.put("/admin/api/settings", json=["not", "an", "object"], headers=ADMIN)
    assert response.status_code == 400


def test_the_server_sends_codes_not_sentences(client):
    """Every reader-facing string lives in the catalogues, in both languages.

    A message composed on the server would be a second translation path, and it
    would be English-only — which PRODUCT.md forbids outright.
    """
    body = client.put("/admin/api/settings", json={"model": "nope"}, headers=ADMIN).get_json()

    for error in body["errors"]:
        assert set(error) <= {"field", "code", "limit"}
        assert " " not in error["code"], "a code with a space is a sentence"


def test_every_error_code_has_a_string_in_both_catalogues():
    """The codes are only useful if the console can say them out loud."""
    import yaml

    codes = set()
    for value in (
        "not_allowed",
        "above_ceiling",
        "out_of_range",
        "not_a_number",
        "not_a_positive_integer",
        "unknown_setting",
        "storage_unavailable",
    ):
        codes.add(value)

    for name in ("en", "ar"):
        with open(f"web/i18n/{name}.yaml", encoding="utf-8") as handle:
            catalog = yaml.safe_load(handle)
        available = set(catalog["runtime"]["admin"]["errors"])
        assert codes <= available, f"{name}.yaml is missing {sorted(codes - available)}"


# ── Model parameter contracts ────────────────────────────────────────────────


def test_a_reasoning_model_sends_neither_max_tokens_nor_temperature(monkeypatch):
    """The incompatibility that would have 400'd every request.

    Reasoning models reject `max_tokens` (they need `max_completion_tokens`,
    which also counts reasoning tokens) and reject `temperature` outright.
    Hardcoding the old shape is why adding one would have taken generation down.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from web.services.openai_app import OpenAIHandler

    kwargs = OpenAIHandler({"model": "gpt-5.6-luna"})._request_kwargs(4096, 0.3)

    assert "max_tokens" not in kwargs
    assert kwargs["max_completion_tokens"] == 4096
    assert "temperature" not in kwargs


def test_an_ordinary_model_keeps_the_shape_it_always_had(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from web.services.openai_app import OpenAIHandler

    kwargs = OpenAIHandler({"model": "gpt-4o-mini"})._request_kwargs(4096, 0.3)

    assert kwargs["max_tokens"] == 4096
    assert kwargs["temperature"] == 0.3
    assert "max_completion_tokens" not in kwargs
    assert "reasoning_effort" not in kwargs


def test_reasoning_effort_is_only_sent_when_chosen(monkeypatch):
    """Absent means "use the model's own default", which is not ours to guess."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from web.services.openai_app import OpenAIHandler

    unset = OpenAIHandler({"model": "gpt-5.6-luna"})._request_kwargs(100, 0.1)
    chosen = OpenAIHandler({"model": "gpt-5.6-luna", "reasoning_effort": "none"})._request_kwargs(
        100, 0.1
    )

    assert "reasoning_effort" not in unset
    assert chosen["reasoning_effort"] == "none"


def test_an_effort_level_the_model_does_not_offer_is_refused(service):
    """The levels differ per model — Luna has `none`, Nano's floor is `minimal`.
    A shared list would offer a value the API then rejects."""
    errors = service.update({"model": "gpt-5.6-luna", "reasoning_effort": "minimal"}, actor=ACTOR)
    assert [e.code for e in errors] == ["not_allowed"]
    assert "none" in errors[0].limit


def test_effort_on_a_non_reasoning_model_is_refused(service):
    errors = service.update({"model": "gpt-4o-mini", "reasoning_effort": "high"}, actor=ACTOR)
    assert [e.code for e in errors] == ["reasoning_not_supported"]


def test_switching_away_from_a_reasoning_model_catches_the_stale_effort(service):
    """Another invalid pair assembled from two individually valid values: the
    effort was fine for the old model and is meaningless to the new one."""
    assert (
        service.update(
            {"model": "gpt-5.6-luna", "reasoning_effort": "high", "max_tokens": 4096},
            actor=ACTOR,
        )
        == []
    )

    errors = service.update({"model": "gpt-4o-mini"}, actor=ACTOR)
    assert [e.code for e in errors] == ["reasoning_not_supported"]
