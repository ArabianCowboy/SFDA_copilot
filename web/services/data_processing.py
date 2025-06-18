"""
SFDA Copilot – PDF → Chunks → Embeddings pipeline
=================================================

Refactored for clarity, maintainability and PEP 8 compliance.
All functional behaviour preserved.

• Extracts text from regulatory / pharmacovigilance PDFs
• Cleans and splits text into overlapping chunks
• Persists metadata to CSV, TF‑IDF assets to disk
• Builds a FAISS ANN index from chosen embedding backend
"""

from __future__ import annotations

# ────────────────────────────── std‑lib ──────────────────────────────
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List

# Ensure project root is on `sys.path` (kept from original script)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# ─────────────────────────── 3rd‑party libs ──────────────────────────
import faiss
import numpy as np
import pandas as pd
import pickle
import PyPDF2
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sklearn.feature_extraction.text import TfidfVectorizer
from tqdm import tqdm

# ──────────────────────────── local modules ──────────────────────────
from web.utils.config_loader import config
from web.utils.openai_client import OpenAIClientManager
from web.utils.local_embedding_client import LocalEmbeddingClient

# ───────────────────────────── constants ─────────────────────────────
CHUNKS_CSV_NAME = "chunks_data.csv"
TFIDF_VECTORIZER_NAME = "tfidf_vectorizer.pkl"
TFIDF_MATRIX_NAME = "tfidf_matrix.pkl"
FAISS_INDEX_NAME = "faiss_index.bin"
DEFAULT_TFIDF_MAX_FEATURES = 5_000

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

        # Embedding backend selection
        embedding_type = config.get("search_engine", "embedding_type", "local")
        if embedding_type == "openai":
            self.embedding_client = OpenAIClientManager()
            self.embedding_dimension = 1_536  # openai text‑embedding‑ada‑002
        else:
            self.embedding_client = LocalEmbeddingClient()
            self.embedding_dimension = self.embedding_client.embedding_dimension

        # Guarantee output directory exists
        self.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────── public API ──────────────────────────
    def process_all_documents(self) -> bool:
        """High‑level orchestrator. Returns *True* on success."""
        LOGGER.info("Starting document processing …")
        categories: Dict[str, Path] = {
            "regulatory": self.REGULATORY_DIR,
            "pharmacovigilance": self.PHARMA_DIR,
            "veterinary": self.VETERINARY_DIR,
            "biological": self.BIOLOGICAL_DIR,
        }

        chunks: List[Dict[str, str | int]] = []

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
                pages_data = self._extract_text_from_pdf(pdf_path)
                if not pages_data:
                    LOGGER.warning("No text extracted from %s – skipped.", pdf_path.name)
                    continue

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
        self._persist_dataframe(df)
        self._persist_tfidf(df["text"])
        self._create_faiss_index(df["text"])

        LOGGER.info("Document processing completed successfully ✓")
        return True

    # ────────────────────────── private helpers ──────────────────────
    def _extract_text_from_pdf(self, path: Path) -> List[Dict[str, str | int]]:
        """Read *path* and return a list of page‑text dictionaries."""
        try:
            with path.open("rb") as file:
                reader = PyPDF2.PdfReader(file)
                pages: List[Dict[str, str | int]] = []

                for page_idx, page in enumerate(reader.pages, start=1):
                    raw_text = page.extract_text() or ""
                    cleaned = self._clean_text(raw_text)
                    if cleaned:
                        pages.append({"text": cleaned, "page": page_idx})
            return pages
        except Exception as exc:
            LOGGER.error("Failed to read %s: %s", path.name, exc)
            return []

    @staticmethod
    def _clean_text(text: str) -> str:
        """Normalise whitespace & remove non‑printables."""
        text = re.sub(r"\n+", "\n", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^\x20-\x7E\n]", "", text)
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

    def _persist_dataframe(self, df: pd.DataFrame) -> None:
        out_path = self.PROCESSED_DATA_DIR / CHUNKS_CSV_NAME
        df.to_csv(out_path, index=False)
        LOGGER.info("Chunk metadata saved → %s (%d rows)", out_path, len(df))

    def _persist_tfidf(self, texts: pd.Series) -> None:
        LOGGER.info("Building TF‑IDF matrix …")
        vectorizer = TfidfVectorizer(max_features=DEFAULT_TFIDF_MAX_FEATURES)
        matrix = vectorizer.fit_transform(texts)

        with open(self.PROCESSED_DATA_DIR / TFIDF_VECTORIZER_NAME, "wb") as f:
            pickle.dump(vectorizer, f)
        with open(self.PROCESSED_DATA_DIR / TFIDF_MATRIX_NAME, "wb") as f:
            pickle.dump(matrix, f)

        LOGGER.info("TF‑IDF artefacts saved.")

    def _create_faiss_index(self, texts: pd.Series) -> None:
        """Compute embeddings & persist FAISS index (FlatL2)."""
        try:
            embeddings = self._get_embeddings(texts.tolist())
            index = faiss.IndexFlatL2(self.embedding_dimension)
            index.add(np.array(embeddings).astype("float32"))

            faiss.write_index(index, str(self.PROCESSED_DATA_DIR / FAISS_INDEX_NAME))
            LOGGER.info("FAISS index saved ✓")
        except Exception as exc:
            LOGGER.error("FAISS index creation failed: %s", exc)

    # Embeddings ------------------------------------------------------
    def _get_embeddings(self, texts: List[str]) -> np.ndarray:
        """Delegate to configured embedding client."""
        return self.embedding_client.get_embeddings(texts, self.embedding_batch_size)


# ──────────────────────────── entry‑point ────────────────────────────
if __name__ == "__main__":
    success = DataProcessor().process_all_documents()
    sys.exit(0 if success else 1)
