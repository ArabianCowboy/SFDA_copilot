"""
SFDA Copilot – PDF → Chunks → Embeddings pipeline
=================================================

Refactored for clarity, maintainability and PEP 8 compliance.
All functional behaviour preserved.

• Extracts text from regulatory / pharmacovigilance PDFs
• Cleans and splits text into overlapping chunks
• Persists metadata to CSV, TF‑IDF assets to disk
• Builds a FAISS ANN index from chosen embedding backend

Build lifecycle
----------------
Every run of :meth:`DataProcessor.process_all_documents` writes its output
into a new, uniquely-named build directory under
``web/processed_data/builds/<build_id>/`` (never directly into the live
paths), fully validates the result, and only then "activates" it by
flipping ``web/processed_data/active_build.txt`` — see
:mod:`web.services.build_registry` for the shared machinery. A failed or
partial run leaves the previously-active build completely untouched.
"""

from __future__ import annotations

# ────────────────────────────── std‑lib ──────────────────────────────
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Must be set before PyTorch/sentence-transformers loads to prevent
# segfault during interpreter shutdown on macOS arm64 (Python 3.14+).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Ensure project root is on `sys.path` (kept from original script)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# ─────────────────────────── 3rd‑party libs ──────────────────────────
import faiss
import numpy as np
import pandas as pd
import pickle
import PyPDF2
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sklearn.feature_extraction.text import TfidfVectorizer
from tqdm import tqdm

# ──────────────────────────── local modules ──────────────────────────
from web.utils.config_loader import config
from web.utils.embedding_helpers import get_embedding_client
from web.services.search_exceptions import EmbeddingError
from web.services.build_registry import (
    CHUNKS_CSV_NAME,
    EXTRACTION_CHUNKING_VERSION,
    FAISS_INDEX_NAME,
    TFIDF_MATRIX_NAME,
    TFIDF_VECTORIZER_NAME,
    BuildValidationError,
    activate_build,
    build_dir_for,
    extract_embedding_model_name,
    new_build_id,
    validate_build_dir,
    write_manifest,
)

# ───────────────────────────── constants ─────────────────────────────
DEFAULT_TFIDF_MAX_FEATURES = 5_000

# If more than this fraction of a build's embeddings come back as exact
# all-zero vectors, the build is aborted rather than activated. Zero vectors
# are the documented failure fallback of the embedding clients (see
# web/utils/local_embedding_client.py / openai_client.py) when embedding
# generation errors out for a batch — a real sentence embedding is never
# exactly all-zero, so any non-trivial fraction of them is a strong signal
# that embedding generation was silently failing during this run.
ZERO_VECTOR_FAILURE_THRESHOLD = 0.005  # 0.5%

# Tolerance used when empirically detecting whether embeddings are
# unit-normalised, for the build manifest's "normalization" field.
NORMALIZATION_TOLERANCE = 1e-3

TABLE_REGEXES = [
    r"\+[-+]+\+",                  # ASCII tables
    r"\|.*\|",                     # Pipe‑delimited tables
    r"\s{2,}.+\s{2,}",             # Space‑aligned columns
    r"<table.*?>",                 # HTML tables
]

# ──────────────────────────── logging cfg  ───────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("sfda.dataprocessor")


class DataProcessingError(Exception):
    """Raised when a build step produces invalid or internally-inconsistent output.

    These are deliberately allowed to propagate out of the ``_persist_*`` /
    ``_create_faiss_index`` helpers (rather than being logged and swallowed)
    so that :meth:`DataProcessor.process_all_documents` can never report
    success while a build step actually failed.
    """


# ──────────────────────────── module helpers ──────────────────────────
def _detect_normalization(embeddings: np.ndarray) -> Dict[str, Any]:
    """Empirically determine whether *embeddings* are (approximately) unit-length.

    This measures the actual produced vectors rather than trusting any one
    embedding client's internals (normalization behaviour differs by
    provider/model and isn't part of the shared ``EmbeddingClient``
    interface), so it stays correct regardless of which provider is
    configured.
    """
    if embeddings.size == 0:
        return {
            "normalized": None,
            "method": "unknown",
            "mean_vector_norm": None,
        }

    norms = np.linalg.norm(embeddings, axis=1)
    mean_norm = float(np.mean(norms))
    std_norm = float(np.std(norms))

    is_normalized = bool(np.allclose(norms, 1.0, atol=NORMALIZATION_TOLERANCE)) or (
        abs(mean_norm - 1.0) < 0.05 and std_norm < 0.05
    )

    return {
        "normalized": is_normalized,
        "method": "l2_unit_norm" if is_normalized else "none_detected",
        "mean_vector_norm": mean_norm,
        "std_vector_norm": std_norm,
    }


# ──────────────────────────── main class ─────────────────────────────
class DataProcessor:
    """End‑to‑end processor for SFDA PDF knowledge‑base."""

    # Directory names are unlikely to change at runtime → class attrs
    RAW_DATA_DIR = Path("data")
    PROCESSED_DATA_DIR = Path("web/processed_data")
    REGULATORY_DIR = RAW_DATA_DIR / "regulatory"
    PHARMA_DIR = RAW_DATA_DIR / "pharmacovigilance"
    VETERINARY_DIR = RAW_DATA_DIR / "Veterinary_Medicines"
    BIOLOGICAL_DIR = RAW_DATA_DIR / "Biological_Products_and_Quality_Control"

    def __init__(self) -> None:
        """Load settings, prepare embedding client and paths."""
        self.chunk_size: int = config.get("data_processing", "chunk_size", 7_000)
        self.chunk_overlap: int = config.get("data_processing", "chunk_overlap", 400)
        self.embedding_batch_size: int = config.get(
            "data_processing", "embedding_batch_size", 100
        )

        embedding_type = config.get("search_engine", "embedding_type", "local")
        self.embedding_type = embedding_type
        try:
            self.embedding_client = get_embedding_client(embedding_type)
            self.embedding_dimension = self.embedding_client.embedding_dimension
        except Exception as exc:
            # Cross-provider fallback is unsafe because the persisted FAISS
            # index must use the same embedding model/vector space as queries.
            raise EmbeddingError(
                f"Failed to initialize '{embedding_type}' embedding provider."
            ) from exc

        # Guarantee output directory exists
        self.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────── public API ──────────────────────────
    def process_all_documents(self) -> bool:
        """High‑level orchestrator.

        Extracts and chunks every source PDF, then builds a brand-new,
        uniquely-named build directory containing the chunk metadata,
        TF-IDF assets, FAISS index, and a ``manifest.json`` describing the
        build. The new build is fully validated before it is "activated"
        (made live) — a failed or partial run never touches whatever build
        was previously active.

        Returns:
            ``True`` only if a new build was produced, validated, *and*
            activated. ``False`` on any failure — including build-step
            failures that used to be silently swallowed.
        """
        LOGGER.info("Starting document processing …")
        categories: Dict[str, Path] = {
            "regulatory": self.REGULATORY_DIR,
            "pharmacovigilance": self.PHARMA_DIR,
            "veterinary": self.VETERINARY_DIR,
            "biological": self.BIOLOGICAL_DIR,
        }

        chunks: List[Dict[str, str | int]] = []
        skipped_documents: List[Dict[str, str]] = []
        documents_processed = 0

        for category, directory in categories.items():
            if not directory.exists():
                LOGGER.warning("Directory %s not found – skipped.", directory)
                continue

            pdf_files = sorted(p for p in directory.iterdir() if p.suffix.lower() == ".pdf")
            if not pdf_files:
                LOGGER.warning("No PDFs in %s – skipped.", directory)
                continue

            LOGGER.info("Processing %s documents (%d files)…", category, len(pdf_files))
            for pdf_path in tqdm(pdf_files, desc=f"[{category}]"):
                pages_data, skip_reason = self._extract_text_from_pdf(pdf_path)
                if not pages_data:
                    LOGGER.warning(
                        "No text extracted from %s – skipped (%s).",
                        pdf_path.name,
                        skip_reason,
                    )
                    skipped_documents.append(
                        {
                            "filename": pdf_path.name,
                            "category": category,
                            "reason": skip_reason or "No extractable text.",
                        }
                    )
                    continue

                documents_processed += 1
                page_chunks = self._split_into_chunks(pages_data)
                for idx, chunk_info in enumerate(page_chunks):
                    chunks.append(
                        {
                            "text": chunk_info["text"],
                            "category": category,
                            "document": pdf_path.name,
                            "page": chunk_info["page"],
                            "chunk_id": f"{pdf_path.name}_p{chunk_info['page']}_{idx}",
                        }
                    )

        if not chunks:
            LOGGER.error("No data chunks produced. Aborting.")
            return False

        df = pd.DataFrame(chunks)

        build_id = new_build_id()
        build_dir = build_dir_for(self.PROCESSED_DATA_DIR, build_id)
        build_dir.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Building new index version '%s' in %s", build_id, build_dir)

        try:
            self._persist_dataframe(df, build_dir)
            self._persist_tfidf(df["text"], build_dir)
            embeddings_meta = self._create_faiss_index(df["text"], build_dir)

            manifest = self._build_manifest(
                build_id=build_id,
                chunk_count=len(df),
                documents_processed=documents_processed,
                skipped_documents=skipped_documents,
                embeddings_meta=embeddings_meta,
            )
            write_manifest(build_dir, manifest)

            # Read the build back from disk and confirm every artifact is
            # present, readable, and internally consistent — this is what
            # gates activation, not just "no exception was raised above".
            validation = validate_build_dir(build_dir)
            LOGGER.info(
                "Build '%s' validated: %d chunks, %d-dim vectors.",
                build_id,
                validation.chunk_count,
                validation.embedding_dimension,
            )
        except Exception:
            LOGGER.error(
                "Build '%s' failed — the previously-active build (if any) "
                "remains untouched and live.",
                build_id,
                exc_info=True,
            )
            return False

        activate_build(self.PROCESSED_DATA_DIR, build_id)
        LOGGER.info(
            "Document processing completed successfully ✓ "
            "(build=%s, chunks=%d, documents=%d, skipped=%d)",
            build_id,
            len(df),
            documents_processed,
            len(skipped_documents),
        )
        return True

    # ────────────────────────── private helpers ──────────────────────
    def _extract_text_from_pdf(
        self, path: Path
    ) -> tuple[List[Dict[str, str | int]], str | None]:
        """Read *path* and return ``(page-text dicts, skip_reason)``.

        ``skip_reason`` is ``None`` when at least one page yielded
        extractable text; otherwise it is a short, specific explanation
        suitable for recording in the build manifest's skipped-documents
        list.
        """
        try:
            with path.open("rb") as file:
                reader = PyPDF2.PdfReader(file)
                pages: List[Dict[str, str | int]] = []

                for page_idx, page in enumerate(reader.pages, start=1):
                    raw_text = page.extract_text() or ""
                    cleaned = self._clean_text(raw_text)
                    if cleaned:
                        pages.append({"text": cleaned, "page": page_idx})

            if not pages:
                return [], (
                    "No extractable text on any page (PyPDF2 returned empty "
                    "text for every page — likely a scanned/image-only PDF "
                    "or a font/encoding issue)."
                )
            return pages, None
        except Exception as exc:
            LOGGER.error("Failed to read %s: %s", path.name, exc)
            return [], f"Failed to open/parse PDF: {exc}"

    @staticmethod
    def _clean_text(text: str) -> str:
        """Normalise whitespace & remove control characters, preserving Unicode letters (including Arabic)."""
        text = re.sub(r"\n+", "\n", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
        return text.strip()

    @staticmethod
    def _has_table(text: str) -> bool:
        """Heuristic table detection."""
        return any(re.search(pattern, text) for pattern in TABLE_REGEXES)

    def _split_into_chunks(
        self, pages_data: List[Dict[str, str | int]]
    ) -> List[Dict[str, str | int]]:
        """Chunk each page using adaptive sizes (tables vs plain text)."""
        chunks: List[Dict[str, str | int]] = []

        for page_info in pages_data:
            is_table = self._has_table(str(page_info["text"]))
            size = 3_000 if is_table else self.chunk_size
            overlap = 600 if is_table else self.chunk_overlap

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=size,
                chunk_overlap=overlap,
                length_function=len,
                separators=["\n\n", "\n", ". ", "? ", "! ", " ", ""],
                is_separator_regex=False,
            )

            try:
                for chunk in splitter.split_text(str(page_info["text"])):
                    if not chunk.strip():
                        continue
                    chunks.append(
                        {
                            "text": chunk,
                            "page": page_info["page"],
                            "chunk_type": "table" if is_table else "text",
                        }
                    )
            except ValueError as exc:  # raised by text‑splitter on bad input
                LOGGER.error("Chunking error (page %s): %s", page_info["page"], exc)

        return chunks

    def _persist_dataframe(self, df: pd.DataFrame, build_dir: Path) -> None:
        out_path = build_dir / CHUNKS_CSV_NAME
        df.to_csv(out_path, index=False)
        LOGGER.info("Chunk metadata saved → %s (%d rows)", out_path, len(df))

    def _persist_tfidf(self, texts: pd.Series, build_dir: Path) -> None:
        """Build and persist TF-IDF assets. Raises :class:`DataProcessingError`
        on any inconsistency (nothing here is caught-and-logged silently)."""
        LOGGER.info("Building TF‑IDF matrix …")
        vectorizer = TfidfVectorizer(max_features=DEFAULT_TFIDF_MAX_FEATURES)
        matrix = vectorizer.fit_transform(texts)

        if matrix.shape[0] != len(texts):
            raise DataProcessingError(
                f"TF-IDF matrix row count ({matrix.shape[0]}) does not match "
                f"the number of input chunks ({len(texts)})."
            )

        with open(build_dir / TFIDF_VECTORIZER_NAME, "wb") as f:
            pickle.dump(vectorizer, f)
        with open(build_dir / TFIDF_MATRIX_NAME, "wb") as f:
            pickle.dump(matrix, f)

        LOGGER.info("TF‑IDF artefacts saved → %s", build_dir)

    def _create_faiss_index(self, texts: pd.Series, build_dir: Path) -> Dict[str, Any]:
        """Compute embeddings & persist FAISS index (FlatL2).

        Unlike the previous implementation, this does **not** catch and log
        failures — embedding generation errors, shape mismatches, and a
        high fraction of all-zero "placeholder" vectors all raise
        :class:`DataProcessingError` (or propagate the underlying exception)
        so the caller cannot mistake a broken build for a successful one.

        Returns:
            A dict of embedding metadata (vector count, zero-vector count,
            normalization info) to be folded into the build manifest.
        """
        embeddings = self._get_embeddings(texts.tolist())
        embeddings_array = np.asarray(embeddings, dtype="float32")

        if embeddings_array.ndim != 2 or embeddings_array.shape[0] != len(texts):
            raise DataProcessingError(
                f"Embedding output shape {embeddings_array.shape} does not "
                f"match the expected chunk count ({len(texts)})."
            )
        if embeddings_array.shape[1] != self.embedding_dimension:
            raise DataProcessingError(
                f"Embedding client produced {embeddings_array.shape[1]}-dim "
                f"vectors but is configured for embedding_dimension="
                f"{self.embedding_dimension}."
            )

        # Guard against the embedding client's documented failure fallback of
        # substituting all-zero vectors for chunks it failed to embed. A real
        # sentence embedding is never exactly all-zero, so this is a reliable
        # (and provider-agnostic) signal of upstream embedding failures.
        zero_mask = ~embeddings_array.any(axis=1)
        zero_rows = int(np.count_nonzero(zero_mask))
        if zero_rows:
            zero_fraction = zero_rows / len(embeddings_array)
            LOGGER.warning(
                "%d/%d embeddings (%.2f%%) are all-zero vectors — likely "
                "embedding failures upstream.",
                zero_rows,
                len(embeddings_array),
                zero_fraction * 100,
            )
            if zero_fraction > ZERO_VECTOR_FAILURE_THRESHOLD:
                raise DataProcessingError(
                    f"{zero_rows}/{len(embeddings_array)} embeddings "
                    f"({zero_fraction:.2%}) are all-zero vectors, exceeding "
                    f"the {ZERO_VECTOR_FAILURE_THRESHOLD:.1%} failure "
                    "threshold — aborting this build rather than indexing "
                    "corrupted vectors."
                )

        index = faiss.IndexFlatL2(self.embedding_dimension)
        index.add(embeddings_array)

        if index.ntotal != len(texts):
            raise DataProcessingError(
                f"FAISS index row count ({index.ntotal}) does not match the "
                f"expected chunk count ({len(texts)}) after add()."
            )

        out_path = build_dir / FAISS_INDEX_NAME
        faiss.write_index(index, str(out_path))
        LOGGER.info("FAISS index saved → %s (%d vectors)", out_path, index.ntotal)

        normalization = _detect_normalization(embeddings_array)
        return {
            "vector_count": index.ntotal,
            "zero_vector_count": zero_rows,
            "normalization": normalization,
        }

    def _build_manifest(
        self,
        *,
        build_id: str,
        chunk_count: int,
        documents_processed: int,
        skipped_documents: List[Dict[str, str]],
        embeddings_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assemble the build's "ID card" (``manifest.json``).

        Recorded here so that :class:`~web.services.search_index.SearchIndex`
        can refuse to load a build whose embedding model/dimension doesn't
        match what the app is currently configured to run, instead of
        silently loading a mismatched index.
        """
        return {
            "build_id": build_id,
            "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "extraction_chunking_version": EXTRACTION_CHUNKING_VERSION,
            "embedding_type": self.embedding_type,
            "embedding_model_name": extract_embedding_model_name(self.embedding_client),
            "embedding_dimension": self.embedding_dimension,
            "embedding_normalization": embeddings_meta.get("normalization"),
            "embedding_zero_vector_count": embeddings_meta.get("zero_vector_count"),
            "chunk_count": chunk_count,
            "documents_processed": documents_processed,
            "documents_skipped": len(skipped_documents),
            "skipped_documents": skipped_documents,
            "chunking": {
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            },
        }

    # Embeddings ------------------------------------------------------
    def _get_embeddings(self, texts: List[str]) -> np.ndarray:
        """Delegate to configured embedding client."""
        return self.embedding_client.get_embeddings(texts, self.embedding_batch_size)


# ──────────────────────────── entry‑point ────────────────────────────
if __name__ == "__main__":
    success = DataProcessor().process_all_documents()
    sys.exit(0 if success else 1)
