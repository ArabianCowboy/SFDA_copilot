"""
Build registry — shared constants and helpers for versioned, atomic search-index builds.

Problem this solves
--------------------
Historically ``data_processing.py`` wrote its four output artifacts
(``chunks_data.csv``, ``tfidf_vectorizer.pkl``, ``tfidf_matrix.pkl``,
``faiss_index.bin``) directly into the live ``web/processed_data/`` directory
that the running Flask app reads from. A partially-failed run could leave
that directory in a corrupt, inconsistent state while the app was still
serving traffic from it.

This module implements the fix: every run of the pipeline writes into its
own uniquely-named, timestamped build directory under
``web/processed_data/builds/<build_id>/``, gets fully validated there, and is
only "activated" (made live) by flipping a small pointer file
(``web/processed_data/active_build.txt``) as the very last step. A failed or
partial run never touches the previously-active build.

This module is intentionally shared between:
  * :mod:`web.services.data_processing` — the offline pipeline that
    *produces* builds and activates them.
  * :mod:`web.services.search_index` — the runtime loader that *consumes*
    the currently-active build (falling back to the legacy flat layout if
    no build has ever been activated).

so that the row-count consistency check is defined in exactly one place.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import pandas as pd

# datetime.UTC is Python 3.11+; the VPS production floor is 3.10.
UTC = timezone.utc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Canonical artifact filenames written inside every build directory. These
# intentionally match the defaults that ``search_engine.py`` derives from
# ``config.yaml``'s (currently absent) ``filenames`` section.
CHUNKS_CSV_NAME = "chunks_data.csv"
TFIDF_VECTORIZER_NAME = "tfidf_vectorizer.pkl"
TFIDF_MATRIX_NAME = "tfidf_matrix.pkl"
FAISS_INDEX_NAME = "faiss_index.bin"
MANIFEST_NAME = "manifest.json"

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    CHUNKS_CSV_NAME,
    TFIDF_VECTORIZER_NAME,
    TFIDF_MATRIX_NAME,
    FAISS_INDEX_NAME,
    MANIFEST_NAME,
)

BUILDS_SUBDIR = "builds"
ACTIVE_BUILD_POINTER_NAME = "active_build.txt"

# Bump this string whenever the extraction/chunking *logic* changes in a way
# that would make old and new chunks meaningfully different (e.g. switching
# PDF extractors, changing the chunk-splitting algorithm). It is recorded in
# every build's manifest so a human (or future validation code) can tell
# which generation of the pipeline produced a given index.
EXTRACTION_CHUNKING_VERSION = "v1"


class BuildValidationError(Exception):
    """Raised when a build directory fails validation.

    Raised both by the pipeline (before activation — a failed validation
    here means the previously-active build is left untouched) and available
    for reuse by anything else that wants to sanity-check a build directory
    on disk (e.g. an operator running the CLI in this module).
    """


# ---------------------------------------------------------------------------
# Build identity / paths
# ---------------------------------------------------------------------------


def new_build_id() -> str:
    """Return a sortable, unique, filesystem-safe build identifier.

    Uses a compact ISO-8601-like timestamp (UTC, microsecond precision,
    no ``:`` characters since those are illegal in Windows filenames).
    """
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def builds_root(processed_data_dir: Path) -> Path:
    """Return the directory that holds every versioned build."""
    return processed_data_dir / BUILDS_SUBDIR


def build_dir_for(processed_data_dir: Path, build_id: str) -> Path:
    """Return the directory for a specific build id (may not exist yet)."""
    return builds_root(processed_data_dir) / build_id


def active_build_pointer_path(processed_data_dir: Path) -> Path:
    return processed_data_dir / ACTIVE_BUILD_POINTER_NAME


def read_active_build_id(processed_data_dir: Path) -> str | None:
    """Return the currently-active build id, or ``None`` if unset.

    ``None`` covers both "the pointer file doesn't exist yet" (a fresh
    checkout that predates this build system, or one that still uses the
    legacy flat ``web/processed_data/*`` layout) and "the pointer file is
    empty".
    """
    pointer = active_build_pointer_path(processed_data_dir)
    if not pointer.exists():
        return None
    build_id = pointer.read_text(encoding="utf-8").strip()
    return build_id or None


def resolve_active_build_dir(processed_data_dir: Path) -> Path | None:
    """Resolve the active build directory, or ``None`` if there isn't one.

    Returns ``None`` (rather than raising) when:
      * no build has ever been activated (no pointer file) — callers should
        fall back to the legacy flat layout for backward compatibility, or
      * the pointer references a build directory that no longer exists on
        disk (e.g. manually deleted) — this is logged loudly since it is
        almost certainly an operator mistake.
    """
    build_id = read_active_build_id(processed_data_dir)
    if not build_id:
        return None
    candidate = build_dir_for(processed_data_dir, build_id)
    if not candidate.is_dir():
        logger.error(
            "active_build.txt points to build '%s' (%s), but that directory "
            "does not exist on disk. Falling back to the legacy flat layout "
            "if present.",
            build_id,
            candidate,
        )
        return None
    return candidate


def list_build_ids(processed_data_dir: Path) -> list[str]:
    """Return all known build ids under ``builds/``, oldest first."""
    root = builds_root(processed_data_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def write_manifest(build_dir: Path, manifest: dict[str, Any]) -> Path:
    """Serialize *manifest* to ``manifest.json`` inside *build_dir*."""
    path = build_dir / MANIFEST_NAME
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False, sort_keys=True)
    return path


def load_manifest(build_dir: Path) -> dict[str, Any]:
    """Read and parse ``manifest.json`` from *build_dir*."""
    path = build_dir / MANIFEST_NAME
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Embedding client introspection
# ---------------------------------------------------------------------------


def extract_embedding_model_name(client: Any) -> str | None:
    """Best-effort extraction of a human-readable model name from *client*.

    The ``EmbeddingClient`` interface (``web/utils/embedding_helpers.py``)
    does not standardize a "model name" attribute — different providers
    expose it under different names (``LocalEmbeddingClient.model_name``,
    ``OpenAIClientManager.embedding_model``). This duck-types across the
    known conventions instead of assuming any one provider's internals.
    """
    for attr in ("model_name", "embedding_model", "model"):
        value = getattr(client, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def rows_consistent(df_rows: int, tfidf_rows: int, faiss_rows: int) -> bool:
    """Shared predicate for "do these three row counts agree".

    Used by both :mod:`web.services.search_index` (validating whatever is
    currently loaded in memory) and :func:`validate_build_dir` below
    (validating a build directory freshly read from disk), so the
    consistency rule is defined exactly once.
    """
    return df_rows == tfidf_rows == faiss_rows


@dataclass(frozen=True)
class BuildValidationResult:
    chunk_count: int
    faiss_vectors: int
    tfidf_rows: int
    embedding_dimension: int
    manifest: dict[str, Any]


def validate_build_dir(build_dir: Path) -> BuildValidationResult:
    """Fully validate a build directory written to disk.

    Confirms every required artifact exists, is readable, and that the
    FAISS/TF-IDF/DataFrame row counts agree with each other *and* with the
    manifest's own claims. Raises :class:`BuildValidationError` with a
    specific message on the first problem found; raises nothing if the
    build is internally consistent.

    This performs a genuine read-back from disk (not a check of in-memory
    objects still held by the caller) so that it also catches real
    write-time corruption (partial writes, disk errors, etc.), not just
    logic bugs.
    """
    missing = [name for name in REQUIRED_ARTIFACTS if not (build_dir / name).exists()]
    if missing:
        raise BuildValidationError(
            f"Build '{build_dir.name}' is missing required artifact(s): {missing}."
        )

    try:
        manifest = load_manifest(build_dir)
    except Exception as exc:
        raise BuildValidationError(
            f"Build '{build_dir.name}' has an unreadable {MANIFEST_NAME}: {exc}"
        ) from exc

    try:
        df = pd.read_csv(build_dir / CHUNKS_CSV_NAME)
    except Exception as exc:
        raise BuildValidationError(
            f"Build '{build_dir.name}' has an unreadable {CHUNKS_CSV_NAME}: {exc}"
        ) from exc

    try:
        with open(build_dir / TFIDF_VECTORIZER_NAME, "rb") as fh:
            pickle.load(fh)  # unpickled only to confirm it is not corrupt
    except Exception as exc:
        raise BuildValidationError(
            f"Build '{build_dir.name}' has an unreadable {TFIDF_VECTORIZER_NAME}: {exc}"
        ) from exc

    try:
        with open(build_dir / TFIDF_MATRIX_NAME, "rb") as fh:
            tfidf_matrix = pickle.load(fh)
    except Exception as exc:
        raise BuildValidationError(
            f"Build '{build_dir.name}' has an unreadable {TFIDF_MATRIX_NAME}: {exc}"
        ) from exc

    try:
        faiss_index = faiss.read_index(str(build_dir / FAISS_INDEX_NAME))
    except Exception as exc:
        raise BuildValidationError(
            f"Build '{build_dir.name}' has an unreadable {FAISS_INDEX_NAME}: {exc}"
        ) from exc

    df_rows = len(df)
    tfidf_rows = tfidf_matrix.shape[0]
    faiss_rows = faiss_index.ntotal

    if df_rows == 0:
        raise BuildValidationError(f"Build '{build_dir.name}' contains zero chunks.")

    if not rows_consistent(df_rows, tfidf_rows, faiss_rows):
        raise BuildValidationError(
            f"Build '{build_dir.name}' has inconsistent row counts — "
            f"DataFrame: {df_rows}, TF-IDF: {tfidf_rows}, FAISS: {faiss_rows}."
        )

    manifest_chunk_count = manifest.get("chunk_count")
    if manifest_chunk_count is not None and manifest_chunk_count != df_rows:
        raise BuildValidationError(
            f"Build '{build_dir.name}' manifest claims chunk_count="
            f"{manifest_chunk_count}, but the on-disk artifacts contain "
            f"{df_rows} rows."
        )

    manifest_dim = manifest.get("embedding_dimension")
    if manifest_dim is not None and manifest_dim != faiss_index.d:
        raise BuildValidationError(
            f"Build '{build_dir.name}' manifest claims embedding_dimension="
            f"{manifest_dim}, but the FAISS index actually has dimension "
            f"{faiss_index.d}."
        )

    return BuildValidationResult(
        chunk_count=df_rows,
        faiss_vectors=faiss_rows,
        tfidf_rows=tfidf_rows,
        embedding_dimension=faiss_index.d,
        manifest=manifest,
    )


# ---------------------------------------------------------------------------
# Activation (the only step that changes what's "live")
# ---------------------------------------------------------------------------


def activate_build(processed_data_dir: Path, build_id: str) -> None:
    """Atomically flip the active-build pointer to *build_id*.

    This must only be called after :func:`validate_build_dir` has passed
    for the target build — this function does not re-validate, by design,
    so that callers control exactly when validation happens relative to
    activation.

    The pointer file itself is small (a single line of text) and is
    written via write-to-temp-then-``os.replace`` so the flip is atomic on
    both POSIX and Windows: readers either see the old build id or the new
    one, never a partially-written file.
    """
    build_dir = build_dir_for(processed_data_dir, build_id)
    if not build_dir.is_dir():
        raise BuildValidationError(
            f"Refusing to activate build '{build_id}': directory {build_dir} does not exist."
        )

    processed_data_dir.mkdir(parents=True, exist_ok=True)
    pointer = active_build_pointer_path(processed_data_dir)
    tmp_pointer = pointer.with_name(pointer.name + ".tmp")
    tmp_pointer.write_text(build_id, encoding="utf-8")
    os.replace(tmp_pointer, pointer)
    logger.info("Activated build '%s' (pointer: %s).", build_id, pointer)


# ---------------------------------------------------------------------------
# Operator CLI — inspect builds and roll back without hand-editing files
# ---------------------------------------------------------------------------


def _cli_list(processed_data_dir: Path) -> None:
    active = read_active_build_id(processed_data_dir)
    build_ids = list_build_ids(processed_data_dir)
    if not build_ids:
        print(f"No builds found under {builds_root(processed_data_dir)}.")
        return

    for build_id in build_ids:
        marker = " * ACTIVE" if build_id == active else ""
        build_dir = build_dir_for(processed_data_dir, build_id)
        try:
            manifest = load_manifest(build_dir)
            summary = (
                f"chunks={manifest.get('chunk_count', '?')} "
                f"docs={manifest.get('documents_processed', '?')} "
                f"skipped={manifest.get('documents_skipped', '?')} "
                f"model={manifest.get('embedding_model_name', '?')}"
            )
        except Exception as exc:
            summary = f"(manifest unreadable: {exc})"
        print(f"{build_id}{marker}  {summary}")

    if active and active not in build_ids:
        print(
            f"\nWARNING: active_build.txt points to '{active}', which is not "
            "a known build directory."
        )


def _cli_activate(processed_data_dir: Path, build_id: str, *, skip_validation: bool) -> int:
    build_dir = build_dir_for(processed_data_dir, build_id)
    if not build_dir.is_dir():
        print(f"ERROR: build '{build_id}' does not exist at {build_dir}.")
        return 1

    if not skip_validation:
        try:
            result = validate_build_dir(build_dir)
        except BuildValidationError as exc:
            print(f"ERROR: refusing to activate '{build_id}' — it fails validation: {exc}")
            return 1
        print(
            f"Validated build '{build_id}': {result.chunk_count} chunks, "
            f"{result.embedding_dimension}-dim vectors."
        )

    activate_build(processed_data_dir, build_id)
    print(f"Activated build '{build_id}'. Restart the Flask app for it to take effect.")
    return 0


def _load_build_document_chunk_counts(build_dir: Path) -> dict[str, int]:
    """Return ``{document_filename: chunk_count}`` for a build directory."""
    df = pd.read_csv(build_dir / CHUNKS_CSV_NAME)
    return df["document"].value_counts().to_dict()


def _cli_diff(processed_data_dir: Path, build_id_a: str, build_id_b: str) -> int:
    """Print a human-readable comparison between two builds.

    Shows manifest-level setting changes (model, dimension, chunking
    params, totals), which source documents were added/removed, which
    existing documents produced a different chunk count (a signal their
    extracted/chunked content actually changed, not just metadata), and
    any change in which documents get silently skipped.
    """
    dir_a = build_dir_for(processed_data_dir, build_id_a)
    dir_b = build_dir_for(processed_data_dir, build_id_b)
    if not dir_a.is_dir():
        print(f"ERROR: build '{build_id_a}' does not exist at {dir_a}.")
        return 1
    if not dir_b.is_dir():
        print(f"ERROR: build '{build_id_b}' does not exist at {dir_b}.")
        return 1

    try:
        manifest_a = load_manifest(dir_a)
        manifest_b = load_manifest(dir_b)
    except Exception as exc:
        print(f"ERROR: could not read one of the manifests: {exc}")
        return 1

    print(f"Comparing build '{build_id_a}' -> '{build_id_b}'\n")

    print("== Settings & totals ==")
    fields = [
        ("embedding_model_name", "Embedding model"),
        ("embedding_dimension", "Embedding dimension"),
        ("extraction_chunking_version", "Extraction/chunking version"),
        ("chunk_count", "Total chunk count"),
        ("documents_processed", "Documents processed"),
        ("documents_skipped", "Documents skipped"),
    ]
    any_setting_changed = False
    for key, label in fields:
        old_val = manifest_a.get(key, "?")
        new_val = manifest_b.get(key, "?")
        if old_val != new_val:
            any_setting_changed = True
            print(f"  {label}: {old_val} -> {new_val}")

    chunking_a = manifest_a.get("chunking", {})
    chunking_b = manifest_b.get("chunking", {})
    if chunking_a != chunking_b:
        any_setting_changed = True
        print(f"  Chunking params: {chunking_a} -> {chunking_b}")

    if not any_setting_changed:
        print("  (no change)")

    try:
        docs_a = _load_build_document_chunk_counts(dir_a)
        docs_b = _load_build_document_chunk_counts(dir_b)
    except Exception as exc:
        print(f"\nERROR: could not read chunk data for document-level diff: {exc}")
        return 1

    added = sorted(set(docs_b) - set(docs_a))
    removed = sorted(set(docs_a) - set(docs_b))
    common = sorted(set(docs_a) & set(docs_b))
    changed = [(d, docs_a[d], docs_b[d]) for d in common if docs_a[d] != docs_b[d]]

    print(f"\n== Documents ({len(docs_a)} -> {len(docs_b)}) ==")
    if added:
        print(f"  Added ({len(added)}):")
        for d in added:
            print(f"    + {d}  ({docs_b[d]} chunks)")
    if removed:
        print(f"  Removed ({len(removed)}):")
        for d in removed:
            print(f"    - {d}  ({docs_a[d]} chunks)")
    if changed:
        print(f"  Chunk count changed ({len(changed)}) — content or chunking differs:")
        for d, old_c, new_c in changed:
            print(f"    ~ {d}  ({old_c} -> {new_c} chunks)")
    if not added and not removed and not changed:
        print("  (identical document set and per-document chunk counts)")

    skipped_a = {d["filename"] for d in manifest_a.get("skipped_documents", [])}
    skipped_b = {d["filename"] for d in manifest_b.get("skipped_documents", [])}
    newly_skipped = sorted(skipped_b - skipped_a)
    no_longer_skipped = sorted(skipped_a - skipped_b)
    if newly_skipped or no_longer_skipped:
        print("\n== Skipped-document changes ==")
        for d in newly_skipped:
            print(f"    now skipped: {d}")
        for d in no_longer_skipped:
            print(f"    no longer skipped: {d}")

    return 0


def main() -> int:
    """CLI entry point for inspecting and rolling back search-index builds.

    Examples::

        python -m web.services.build_registry list
        python -m web.services.build_registry activate 20260803T120000000000Z
        python -m web.services.build_registry diff 20260803T120000000000Z 20260803T220000000000Z

    Rollback is simply "activate an older build id" — every previous build
    is kept on disk untouched, so rolling back is always available as long
    as the desired build directory hasn't been manually deleted.
    """
    parser = argparse.ArgumentParser(
        prog="python -m web.services.build_registry",
        description="Inspect and activate versioned search-index builds.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List all known builds and show which is active.")

    activate_parser = subparsers.add_parser(
        "activate", help="Make an existing build the live one (used for rollback)."
    )
    activate_parser.add_argument("build_id", help="Build id, e.g. 20260803T120000000000Z")
    activate_parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Activate without re-validating the build first (not recommended).",
    )

    diff_parser = subparsers.add_parser(
        "diff", help="Compare two builds: settings, documents added/removed, chunk-count changes."
    )
    diff_parser.add_argument("build_a", help="Older/baseline build id")
    diff_parser.add_argument("build_b", help="Newer build id to compare against build_a")

    args = parser.parse_args()
    # Matches DataProcessor.PROCESSED_DATA_DIR / SearchEngineConfig's default —
    # resolved relative to the current working directory, consistent with how
    # ``python -m web.services.data_processing`` is already run from the repo root.
    processed_data_dir = Path("web/processed_data")

    if args.command == "list":
        _cli_list(processed_data_dir)
        return 0
    if args.command == "activate":
        return _cli_activate(
            processed_data_dir, args.build_id, skip_validation=args.skip_validation
        )
    if args.command == "diff":
        return _cli_diff(processed_data_dir, args.build_a, args.build_b)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
