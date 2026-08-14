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
from typing import Any, Dict, List, Optional, Tuple

from web.utils.config_loader import config

logger = logging.getLogger(__name__)

# The settings an administrator may set. Anything else in a payload is rejected
# rather than ignored: silently dropping an unknown key means an operator who
# mistypes one is told their change was saved.
GENERATION_KEYS: Tuple[str, ...] = (
    "model",
    "temperature",
    "max_tokens",
    "max_context_results",
    "reasoning_effort",
)

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
    limit: Optional[Any] = None

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"field": self.field, "code": self.code}
        if self.limit is not None:
            payload["limit"] = self.limit
        return payload


def allowed_models() -> List[Dict[str, Any]]:
    """The models an administrator may select, from config.yaml."""
    models = config.get("openai", "allowed_models", []) or []
    return [m for m in models if isinstance(m, dict) and m.get("id")]


def model_spec(model_id: str) -> Dict[str, Any]:
    """The model's parameter contract, with the defaults filled in.

    One place decides what a request to a given model may carry, because the
    OpenAI families do not agree: a reasoning model rejects `max_tokens` and
    `temperature` outright, and its accepted effort levels differ from the next
    model's. An unknown id gets the conservative shape — the one every model
    has always accepted.
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


def _model_ceiling(model_id: str) -> Optional[int]:
    return model_spec(model_id)["max_output_tokens"]


def deployed_defaults() -> Dict[str, Any]:
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


def validate(patch: Dict[str, Any], current: Dict[str, Any]) -> List[ValidationError]:
    """Validate the **resulting** settings, not the patch in isolation.

    The distinction is load-bearing. An operator who switches to a model with a
    lower output ceiling, without touching max_tokens, has produced an invalid
    pair from two individually valid values — and every request afterwards
    would 400 at the provider. Merging first is what catches that.
    """
    errors: List[ValidationError] = []

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


class SettingsService:
    """Effective settings, cached in process.

    Loaded lazily on first read and never at ``create_app`` time: a Supabase
    blip at boot must not stop a process whose search index takes minutes to
    load, and the reader-facing product does not need this to serve a question.

    Same scope contract as the other caches here — one worker, RAM, and the
    database is the authority. A write refreshes immediately, so an operator
    never sees their own change lag.
    """

    def __init__(self, backend_provider, ttl_seconds: float = 60.0) -> None:
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
        self._cached: Optional[Dict[str, Any]] = None
        self._loaded_at = 0.0

    @staticmethod
    def _now() -> float:
        import time
        return time.monotonic()

    @property
    def _backend(self):
        return self._backend_provider()

    def _read_overrides(self) -> Dict[str, Any]:
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

    def _overrides(self) -> Dict[str, Any]:
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

    def snapshot(self, *, force: bool = False) -> Dict[str, Any]:
        """The effective settings: deployed defaults with overrides applied."""
        with self._lock:
            fresh = (
                self._cached is not None
                and not force
                and self._now() - self._loaded_at < self._ttl
            )
            if fresh:
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

    def overrides(self) -> Dict[str, Any]:
        """What has actually been changed, for the console to show as such."""
        return {k: v for k, v in self._overrides().items() if k in GENERATION_KEYS}

    def _publish(self, overrides: Dict[str, Any]) -> None:
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

    def update(self, patch: Dict[str, Any], *, actor, on_committed=None) -> List[ValidationError]:
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
                logger.error("Settings read failed during update; refusing to write.", exc_info=True)
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

            # Inside the lock, deliberately. Two overlapping saves would
            # otherwise each store, then build, then swap — and if the first
            # build finished last, generation would settle on the older
            # settings while the store and both responses said the newer. The
            # write is already serialized; the effect has to be too, or the
            # serialization only covers half the operation.
            if on_committed is not None:
                on_committed()
        return []
