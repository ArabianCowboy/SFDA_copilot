"""Runtime settings: what an administrator may change without a deploy.

The store holds **overrides only**. An absent key means "whatever config.yaml
says", so removing an override reverts to the deployed default and a deploy
that changes a default is picked up rather than shadowed by a row written
months earlier.

Nothing here applies a setting to generation. That is Phase 5's job, and the
separation is deliberate: persistence and validation are worth having under
test before anything on the answer path starts reading them.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from typing import Any

from web.utils.config_loader import config

logger = logging.getLogger(__name__)

# The settings an administrator may set. Anything else in a payload is rejected
# rather than ignored: silently dropping an unknown key means an operator who
# mistypes one is told their change was saved.
GENERATION_KEYS: tuple[str, ...] = (
    "model",
    "temperature",
    "max_tokens",
    "max_context_results",
    "reasoning_effort",
)

# A second, parallel key set for settings that are stored in the same
# `app_settings.settings` JSONB document but have nothing to do with
# generation: no pairwise validation against a model's parameter contract, no
# rebuild of the OpenAI handler on write. Kept as its OWN tuple rather than
# folded into GENERATION_KEYS so `validate()` — which merges a patch with
# `deployed_defaults()` and reasons about model/token/effort compatibility —
# never has to grow an "except this one" branch for a boolean.
#
# Sharing the class below rather than living in a standalone module, unlike
# `notification_store.get_purge_retention_days` / `set_purge_retention_days`:
# those read and write the row directly, with no cache and no lock, which is
# fine for a value read once per admin-tab load and is a live lost-update race
# waiting for a second concurrent writer. This key set shares
# `SettingsService._write_lock` instead — the one thing a signup gate,
# checked on every request, genuinely cannot do without.
NON_GENERATION_KEYS: tuple[str, ...] = ("signup_enabled",)

TEMPERATURE_RANGE = (0.0, 2.0)


@dataclass(frozen=True)
class ValidationError:
    """A machine code, not a sentence.

    The client owns every reader-facing string in both languages; a message
    composed here would be a second translation path this app does not have.
    `limit` carries the number the operator needs to see, so the console can
    say "at most 16384" without the server writing the word "most".
    """

    field: str
    code: str
    limit: Any | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"field": self.field, "code": self.code}
        if self.limit is not None:
            payload["limit"] = self.limit
        return payload


def allowed_models() -> list[dict[str, Any]]:
    """The models an administrator may select, from config.yaml."""
    models = config.get("openai", "allowed_models", []) or []
    return [m for m in models if isinstance(m, dict) and m.get("id")]


def model_spec(model_id: object) -> dict[str, Any]:
    """The model's parameter contract, with the defaults filled in.

    One place decides what a request to a given model may carry, because the
    OpenAI families do not agree: a reasoning model rejects `max_tokens` and
    `temperature` outright, and its accepted effort levels differ from the next
    model's. An unknown id gets the conservative shape — the one every model
    has always accepted. ``model_id`` is typed loosely on purpose: callers like
    `validate` pass a value straight out of an untrusted JSON payload, and an
    unknown/wrong-typed id is meant to fall through to that conservative shape
    rather than be rejected before it can be compared.
    """
    entry = next((m for m in allowed_models() if m["id"] == model_id), {})
    return {
        "id": model_id,
        "label": entry.get("label", model_id),
        "max_output_tokens": entry.get("max_output_tokens"),
        "token_param": entry.get("token_param", "max_tokens"),
        "supports_temperature": entry.get("supports_temperature", True),
        "reasoning_efforts": list(entry.get("reasoning_efforts") or []),
    }


def _model_ceiling(model_id: object) -> int | None:
    return model_spec(model_id)["max_output_tokens"]


def deployed_defaults() -> dict[str, Any]:
    """The values config.yaml ships, i.e. what an empty override set means."""
    return {
        "model": config.get("openai", "model", "gpt-4o-mini"),
        "temperature": config.get("openai", "temperature", 0.1),
        "max_tokens": config.get("openai", "max_tokens", 4096),
        "max_context_results": config.get("openai", "max_context_results", 8),
        # None means "do not send it". Absent is the only correct default: a
        # non-reasoning model rejects the parameter, and a reasoning model has
        # its own documented default that we should not second-guess.
        "reasoning_effort": config.get("openai", "reasoning_effort", None),
    }


def deployed_non_generation_defaults() -> dict[str, Any]:
    """The values config.yaml ships for :data:`NON_GENERATION_KEYS`."""
    return {"signup_enabled": config.get("server", "signup_enabled", True)}


def _context_ceiling() -> int:
    """`search_engine.k`, which bounds how many passages may be cited.

    Not a taste limit. `retrieved[i]` must be the same passage as prompt block
    `[i]`, and the retriever cannot return more than k — so a larger value here
    would silently desynchronise the citation indices.
    """
    return int(config.get("search_engine", "k", 8))


def _in_range(value: Any, low: float, high: float) -> bool:
    """Range check that survives absurd input.

    ``float()`` on a Python int of a few thousand digits raises OverflowError,
    and JSON has no integer limit — so a pasted number turned a 422 into a 500.
    Bounds are compared before any conversion, and a NaN fails every comparison
    and is therefore rejected, which is what we want.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return low <= value <= high
    try:
        as_float = float(value)
    except (OverflowError, ValueError, TypeError):
        return False
    return math.isfinite(as_float) and low <= as_float <= high


def validate(patch: dict[str, Any], current: dict[str, Any]) -> list[ValidationError]:
    """Validate the **resulting** settings, not the patch in isolation.

    The distinction is load-bearing. An operator who switches to a model with a
    lower output ceiling, without touching max_tokens, has produced an invalid
    pair from two individually valid values — and every request afterwards
    would 400 at the provider. Merging first is what catches that.
    """
    errors: list[ValidationError] = []

    unknown = sorted(set(patch) - set(GENERATION_KEYS))
    errors.extend(ValidationError(field=key, code="unknown_setting") for key in unknown)

    merged = {**current, **{k: v for k, v in patch.items() if k in GENERATION_KEYS}}

    model = merged.get("model")
    known_ids = [entry["id"] for entry in allowed_models()]
    if known_ids and model not in known_ids:
        errors.append(ValidationError("model", "not_allowed", limit=known_ids))

    temperature = merged.get("temperature")
    low, high = TEMPERATURE_RANGE
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        errors.append(ValidationError("temperature", "not_a_number"))
    elif not _in_range(temperature, low, high):
        errors.append(ValidationError("temperature", "out_of_range", limit=[low, high]))

    max_tokens = merged.get("max_tokens")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
        errors.append(ValidationError("max_tokens", "not_a_positive_integer"))
    else:
        ceiling = _model_ceiling(model)
        if ceiling is not None and max_tokens > ceiling:
            # 422 with the ceiling, never a silent clamp. An operator who typed
            # 32000 for a 16384 model should be told, not quietly corrected —
            # being corrected behind your back is how you stop trusting a
            # control.
            errors.append(ValidationError("max_tokens", "above_ceiling", limit=ceiling))

    passages = merged.get("max_context_results")
    ceiling = _context_ceiling()
    if not isinstance(passages, int) or isinstance(passages, bool) or passages < 1:
        errors.append(ValidationError("max_context_results", "not_a_positive_integer"))
    elif passages > ceiling:
        errors.append(ValidationError("max_context_results", "above_ceiling", limit=ceiling))

    # Reasoning effort is validated against the RESULTING model, which is why
    # this reads from `merged`. Switching from a reasoning model to an ordinary
    # one, without clearing the effort, would otherwise leave a parameter set
    # that the new model rejects outright — an invalid pair assembled from two
    # individually valid values, exactly like the token ceiling above.
    effort = merged.get("reasoning_effort")
    if effort is not None:
        supported = model_spec(model)["reasoning_efforts"] if model else []
        if not supported:
            errors.append(ValidationError("reasoning_effort", "reasoning_not_supported"))
        elif effort not in supported:
            errors.append(ValidationError("reasoning_effort", "not_allowed", limit=supported))

    return errors


def validate_non_generation(patch: dict[str, Any]) -> list[ValidationError]:
    """Validate a :data:`NON_GENERATION_KEYS` patch in isolation.

    Unlike :func:`validate`, this never merges against the resulting state —
    there is exactly one key, it is a boolean, and a boolean cannot be made
    invalid by another boolean's value the way a token ceiling can by a model
    choice.
    """
    errors: list[ValidationError] = []

    unknown = sorted(set(patch) - set(NON_GENERATION_KEYS))
    errors.extend(ValidationError(field=key, code="unknown_setting") for key in unknown)

    if "signup_enabled" in patch:
        value = patch["signup_enabled"]
        # `type(value) is bool`, not `isinstance` — `isinstance(True, int)` is
        # True in Python, and every numeric validator above already carries
        # this exact guard for that reason. Here the test runs the other way:
        # 1, 0, "true" and "false" are all refused rather than coerced.
        if type(value) is not bool:
            errors.append(ValidationError("signup_enabled", "not_a_boolean"))

    return errors


class SettingsService:
    """Effective settings, cached in process.

    Loaded lazily on first read and never at ``create_app`` time: a Supabase
    blip at boot must not stop a process whose search index takes minutes to
    load, and the reader-facing product does not need this to serve a question.

    Same scope contract as the other caches here — one worker, RAM, and the
    database is the authority. A write refreshes immediately, so an operator
    never sees their own change lag.
    """

    def __init__(
        self,
        backend_provider,
        ttl_seconds: float = 60.0,
        operational_ttl_seconds: float = 45.0,
    ) -> None:
        # A provider rather than a backend, so the Supabase client is built on
        # first use rather than at create_app time. Constructing it during
        # startup would put a network dependency in front of a process whose
        # search index takes minutes to load, for a surface most deployments
        # never open.
        self._backend_provider = backend_provider
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        # Separate from the cache lock: a write holds this across I/O, and
        # holding the cache lock across a network call would block every reader.
        self._write_lock = threading.Lock()
        self._cached: dict[str, Any] | None = None
        self._loaded_at = 0.0

        # The NON_GENERATION_KEYS cache slot, entirely separate from the pair
        # above: a flag read must never be served from, or overwrite, the
        # generation snapshot, and vice versa. Its TTL is not the propagation
        # mechanism for a console toggle — a write publishes the committed
        # value immediately, the same way `_publish` does for generation
        # settings below — it only bounds staleness from an edit made outside
        # this process entirely, such as the Supabase SQL editor.
        self._operational_ttl = operational_ttl_seconds
        self._operational_cached: bool | None = None
        self._operational_loaded_at = 0.0
        # True once ANY read of the flag has ever succeeded, in this process.
        # Distinguishes "the store is down, but I know the last value" (serve
        # it, however stale) from "the store is down and I have never once
        # been able to ask" (undetermined — see signup_enabled's docstring).
        self._operational_ever_loaded = False

    @staticmethod
    def _now() -> float:
        import time

        return time.monotonic()

    @property
    def _backend(self):
        return self._backend_provider()

    def _read_overrides(self) -> dict[str, Any]:
        """Strict read. Raises if the store cannot answer.

        Used by :meth:`update`, which replaces the whole document: if a failed
        read were flattened to ``{}`` there, a one-key patch during a transient
        outage would write ``{}`` plus that key — silently deleting every other
        override. The lenient path below is only safe for reads.
        """
        backend = self._backend
        if backend is None:
            raise RuntimeError("no settings backend configured")

        stored = backend.get_settings() or {}
        # The column is JSONB with no object-shape constraint, so a scalar or an
        # array written directly to the row would reach `.items()` and raise.
        # Since startup adopts stored overrides, that turned malformed data into
        # a boot failure — the app would not start at all.
        if not isinstance(stored, dict):
            raise TypeError(f"stored settings must be a JSON object, got {type(stored).__name__}")
        return stored

    def _overrides(self) -> dict[str, Any]:
        """Lenient read for display and snapshots.

        Serves the deployed defaults rather than failing the request. A settings
        outage should cost an operator their overrides, not cost every reader
        their answer — but see :meth:`_read_overrides` for why a write must not
        use this.
        """
        try:
            return self._read_overrides()
        except Exception:
            logger.error("Settings read failed; serving deployed defaults.", exc_info=True)
            return {}

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        """The effective settings: deployed defaults with overrides applied."""
        with self._lock:
            fresh = (
                self._cached is not None and not force and self._now() - self._loaded_at < self._ttl
            )
            if fresh:
                assert self._cached is not None  # `fresh` already checked this
                return dict(self._cached)

        overrides = self._overrides()
        defaults = deployed_defaults()
        # Only known keys, and only values of the right shape. A malformed
        # override reverts to the default instead of propagating; the row is
        # not schema-checked, so this is the only place that can hold the line.
        effective = dict(defaults)
        for key in GENERATION_KEYS:
            if key in overrides:
                effective[key] = overrides[key]

        if validate(effective, defaults):
            logger.error(
                "Stored settings are invalid; serving deployed defaults instead: %r",
                overrides,
            )
            effective = defaults

        with self._lock:
            self._cached = dict(effective)
            self._loaded_at = self._now()
        return dict(effective)

    def overrides(self) -> dict[str, Any]:
        """What has actually been changed, for the console to show as such."""
        return {k: v for k, v in self._overrides().items() if k in GENERATION_KEYS}

    def read_overrides(self) -> dict[str, Any]:
        """:meth:`overrides`, but it raises rather than answering ``{}``.

        For the one caller that has to tell "nothing is overridden" apart from
        "the store did not answer": startup. Both look like an empty document
        through :meth:`overrides`, and they mean opposite things there — the
        first is a process correctly running the deployed defaults, the second
        is a process running them while the console will report something else.

        No backend at all is the first case, not the second, and is answered
        rather than raised: without a service-role key nothing can ever have
        been written, and the console reads through this same service — so both
        sides see the deployed defaults and there is nothing to disagree about.
        """
        if self._backend is None:
            return {}
        return {k: v for k, v in self._read_overrides().items() if k in GENERATION_KEYS}

    def _publish(self, overrides: dict[str, Any]) -> None:
        """Install a known-committed document as the snapshot.

        Deliberately not a re-read. `snapshot(force=True)` after a write goes
        back to the store, and that read is the lenient one — so a store that
        fails in the instant after a successful write would publish the deployed
        defaults while the API reported the change as applied. Publishing what
        was actually committed cannot disagree with what was committed.
        """
        effective = deployed_defaults()
        for key in GENERATION_KEYS:
            if key in overrides:
                effective[key] = overrides[key]
        with self._lock:
            self._cached = dict(effective)
            self._loaded_at = self._now()

    def _invalidate_operational_cache(self) -> None:
        """Force the next read of :data:`NON_GENERATION_KEYS` to hit the store.

        Called after every successful write to the row — including a
        generation-only one via :meth:`update`, which writes the WHOLE
        document back regardless of which keys changed. That makes a
        generation save a write to the flag's storage even though it did not
        touch the flag, and missing this call is the bug this design cannot
        afford: the flag would then read stale for up to its own TTL after
        an unrelated save.

        Deliberately does NOT clear ``_operational_cached`` itself — only
        ``_operational_loaded_at``, which is enough to fail the freshness
        check in :meth:`signup_enabled` and force a real read. Clearing the
        value too used to conflate "this needs revalidating" with "nothing
        was ever read": a generation save immediately followed by a read
        failure would answer ``None`` (undetermined, `503`) instead of the
        last known value, however stale — exactly the fabricated-outage
        failure mode :meth:`signup_enabled` exists to avoid.
        """
        with self._lock:
            self._operational_loaded_at = 0.0

    def signup_enabled(self) -> bool | None:
        """Whether the signup form accepts new accounts right now.

        Three-valued on purpose: ``True``/``False`` is an operator's own
        decision, and ``None`` means "could not determine" — the two must
        stay distinguishable because a caller answers them as a ``403`` and a
        ``503`` respectively, which mean opposite things to a reader.
        ``docs/registrations-pause-plan.md`` §5 is the argument for this
        split over the two-valued fail-open/fail-closed alternatives.

        Publish-on-write, not TTL expiry, is what makes a console toggle
        take effect immediately on this single-worker deployment — see
        :meth:`set_signup_enabled`. The TTL here only bounds staleness from
        an edit made OUTSIDE this process, such as the Supabase SQL editor.
        """
        with self._lock:
            fresh = (
                self._operational_cached is not None
                and self._now() - self._operational_loaded_at < self._operational_ttl
            )
            if fresh:
                return self._operational_cached
            # Captured under the SAME lock as the freshness check, before any
            # I/O starts. `set_signup_enabled` publishes under this lock too,
            # so if its publish lands while the read below is in flight, the
            # loaded_at it wrote will be strictly newer than this snapshot —
            # which is how the write-back below can tell it would be
            # clobbering a fresher value with a stale one, and defer to it
            # instead. Without this, a slow unlocked read racing a concurrent
            # toggle could silently overwrite an operator's fresh "paused"
            # with the stale "open" this call started with.
            baseline_loaded_at = self._operational_loaded_at

        # `self._backend` is a property that resolves the provider closure —
        # for the real app that means `create_client(url, key)`, which can
        # raise on a present-but-malformed URL/key, not just return None for
        # an absent one. It used to be read OUTSIDE this try block, so that
        # raise reached every caller uncaught — and `base_render_context()`
        # (`web/api/app.py`) calls `signup_enabled()` unconditionally on
        # EVERY full-page render, including `/admin` and `/account`, neither
        # of which reads the result. An unguarded raise here would 500 the
        # whole site, not just signup. Found in review (/code-review, 2026-08-26).
        try:
            backend = self._backend
            if backend is None:
                # No service-role key configured. Nothing could ever have been
                # written, so there is nothing to disagree with — answer the
                # deployed default, the same reasoning `read_overrides` already
                # gives for the generation keys.
                return bool(deployed_non_generation_defaults()["signup_enabled"])

            stored = backend.get_settings() or {}
            if not isinstance(stored, dict):
                raise TypeError(
                    f"stored settings must be a JSON object, got {type(stored).__name__}"
                )
        except Exception:
            logger.error("Registrations-pause flag read failed.", exc_info=True)
            with self._lock:
                if self._operational_ever_loaded:
                    # A pause must survive a Supabase blip: serve the last
                    # known value, however stale, rather than silently
                    # reopening — or closing — signups mid-incident.
                    return self._operational_cached
            # Never successfully read in THIS process. Answering the
            # deployed default here would be a fabricated "open" during a
            # cold-start outage; the caller must treat this as undetermined.
            return None

        value = stored.get("signup_enabled")
        if type(value) is not bool:
            # Absent (never overridden) or malformed (the row is JSONB with
            # no shape constraint) both mean "no usable override" — revert
            # to the deployed default rather than propagating garbage.
            value = bool(deployed_non_generation_defaults()["signup_enabled"])

        with self._lock:
            if self._operational_loaded_at > baseline_loaded_at:
                # Someone else — set_signup_enabled's publish, or another
                # concurrent signup_enabled() read — already installed a
                # newer value while this read was in flight. Trust that one
                # instead of overwriting it with what we just read.
                return self._operational_cached
            self._operational_cached = value
            self._operational_loaded_at = self._now()
            self._operational_ever_loaded = True
        return value

    def set_signup_enabled(self, enabled: Any, *, actor) -> list[ValidationError]:
        """Set or clear the registrations-pause override.

        ``enabled=None`` removes the override, reverting to the deployed
        default — the same "null removes" convention :meth:`update` uses for
        generation keys. Takes the SAME ``_write_lock`` as :meth:`update`,
        so a console toggle and a generation save can never interleave a
        read-modify-write and silently discard one of them — the exact race
        `20260814022601_app_settings.sql` declines to solve with a `version`
        column, on the assumption every writer takes this one lock.

        Never rebuilds the OpenAI handler and never runs an ``on_committed``
        hook: a registrations toggle has no business restarting generation.
        """
        errors = validate_non_generation({} if enabled is None else {"signup_enabled": enabled})
        if errors:
            return errors

        backend = self._backend
        if backend is None:
            return [ValidationError("_", "storage_unavailable")]

        with self._write_lock:
            try:
                original = dict(self._read_overrides())
            except Exception:
                logger.error(
                    "Settings read failed during a registrations-pause update; refusing to write.",
                    exc_info=True,
                )
                return [ValidationError("_", "storage_unavailable")]

            # Whole-document read, whole-document write — generation keys in
            # `original` ride along untouched, the same way a generation save
            # leaves `signup_enabled` untouched in the other direction.
            stored = dict(original)
            if enabled is None:
                stored.pop("signup_enabled", None)
            else:
                stored["signup_enabled"] = enabled

            backend.put_settings(stored, actor=actor, before=original, after=dict(stored))
            self._invalidate_operational_cache()

            # Publish the committed value directly rather than re-reading —
            # same reasoning as `_publish` above: a store that fails in the
            # instant after a successful write must not un-publish a change
            # that already happened.
            published = (
                bool(deployed_non_generation_defaults()["signup_enabled"])
                if enabled is None
                else enabled
            )
            with self._lock:
                self._operational_cached = published
                self._operational_loaded_at = self._now()
                self._operational_ever_loaded = True
        return []

    def update(self, patch: dict[str, Any], *, actor, on_committed=None) -> list[ValidationError]:
        """Apply a patch. Returns errors; an empty list means it was written.

        A key set to None is removed, which is how an operator reverts to the
        deployed default — distinct from setting it to the default's current
        value, which would pin it against a future deploy.
        """
        # Unknown keys are checked against the ORIGINAL patch, before None
        # entries are filtered out. Splitting first meant `{"nonsense": null}`
        # became a removal of a key that was never a setting, and was accepted.
        unknown = sorted(set(patch) - set(GENERATION_KEYS))
        if unknown:
            return [ValidationError(field=key, code="unknown_setting") for key in unknown]

        removals = {k for k, v in patch.items() if v is None}
        changes = {k: v for k, v in patch.items() if v is not None}

        backend = self._backend
        if backend is None:
            # No service-role key configured. Refusing is the honest answer:
            # reporting success for a write that went nowhere would be worse
            # than the outage it is reporting.
            return [ValidationError("_", "storage_unavailable")]

        # One writer at a time. The lock spans read, merge, validate and write,
        # because two operators saving disjoint patches would otherwise each
        # read the same document and the later write would silently discard the
        # earlier one. This covers the stated single-worker deployment; a second
        # process would need a database-level compare-and-swap.
        with self._write_lock:
            try:
                original = dict(self._read_overrides())
            except Exception:
                logger.error(
                    "Settings read failed during update; refusing to write.", exc_info=True
                )
                return [ValidationError("_", "storage_unavailable")]

            stored = dict(original)
            stored.update(changes)
            for key in removals:
                stored.pop(key, None)

            # Validate the state that will actually result, defaults included —
            # a removal reverts to the deployed default, which is not the value
            # that was there before it. Harmless while every allowed model
            # shares a ceiling; unsafe the moment one does not.
            defaults = deployed_defaults()
            resulting = {**defaults, **{k: v for k, v in stored.items() if k in GENERATION_KEYS}}
            errors = validate(resulting, defaults)
            if errors:
                return errors

            # The diff is recorded from the override documents, not the
            # effective settings: "somebody set the model" and "the model
            # happens to differ from the default" are different facts, and only
            # the first is an action anyone took.
            committed = backend.put_settings(
                stored, actor=actor, before=original, after=dict(stored)
            )
            # Trust the store's answer over our own copy where it gives one.
            self._publish(committed if isinstance(committed, dict) else stored)
            # This just replaced the WHOLE row, including whatever
            # `signup_enabled` was set to — a write to that key's storage
            # even though this patch never named it. See
            # `_invalidate_operational_cache`'s own docstring.
            self._invalidate_operational_cache()

            # Inside the lock, deliberately. Two overlapping saves would
            # otherwise each store, then build, then swap — and if the first
            # build finished last, generation would settle on the older
            # settings while the store and both responses said the newer. The
            # write is already serialized; the effect has to be too, or the
            # serialization only covers half the operation.
            if on_committed is not None:
                on_committed()
        return []
