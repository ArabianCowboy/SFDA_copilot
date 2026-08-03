"""
Custom exceptions for the search engine subsystem.

These domain-specific exceptions allow callers to distinguish search-related
failures from generic errors and handle them appropriately.
"""


class SearchEngineError(Exception):
    """Base exception for all search engine errors."""


class SearchEngineNotInitializedError(SearchEngineError):
    """Raised when an operation requires the engine but it has not been initialized."""

    def __init__(self, message: str = "Search engine is not initialized.") -> None:
        super().__init__(message)


class DataLoadError(SearchEngineError):
    """Raised when required processed data files cannot be loaded from disk."""

    def __init__(self, message: str, missing_files: list[str] | None = None) -> None:
        self.missing_files = missing_files or []
        super().__init__(message)


class DataDimensionMismatchError(SearchEngineError):
    """Raised when loaded data components have incompatible dimensions."""

    def __init__(
        self,
        message: str,
        dataframe_rows: int = 0,
        tfidf_rows: int = 0,
        faiss_vectors: int = 0,
    ) -> None:
        self.dataframe_rows = dataframe_rows
        self.tfidf_rows = tfidf_rows
        self.faiss_vectors = faiss_vectors
        super().__init__(message)


class EmbeddingError(SearchEngineError):
    """Raised when embedding generation fails."""


class QueryTranslationError(SearchEngineError):
    """Raised when query translation (e.g., Arabic → English) fails."""


class ManifestValidationError(Exception):
    """Raised when a search index build's manifest.json doesn't match the
    currently-configured embedding client (wrong model name and/or vector
    dimension).

    Deliberately **not** a subclass of :class:`SearchEngineError`.
    ``SearchEngine._ensure_initialized`` catches ``(DataLoadError,
    SearchEngineError)`` broadly and degrades to "search unavailable"
    (returns ``False``) rather than raising, on the theory that missing
    processed-data files is a recoverable/expected first-run condition.
    A manifest mismatch is different in kind: it means the on-disk index
    was built for a different embedding model/vector space than the one
    the app is currently configured to query with, so loading it would
    silently return plausible-looking but meaningless search results.
    That must crash application startup rather than degrade quietly — see
    ``web/api/app.py::_initialize_services``, which re-raises this specific
    exception instead of swallowing it like other startup errors.
    """
