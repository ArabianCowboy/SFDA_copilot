"""Load the REAL search artifacts the way production does, and search them.

Every other retrieval test builds its artifacts in ``tmp_path``, so none of them
can tell whether the FAISS index, the pickled TF-IDF objects and the chunk CSV
on THIS machine still load under the installed numpy, pandas, scikit-learn and
faiss. That is the question a Python or dependency upgrade raises, and without
this file the first place it gets answered is gunicorn's ``--preload`` in
production, as a refused start.

Marked ``integration``: neither CI job selects it, because CI has no corpus.
Run it by hand on a machine that has one — and on the VPS, inside a new venv,
BEFORE the service is pointed at that venv (docs/OPERATIONS.md):

    python -m pytest web/tests/test_live_artifacts.py -m integration

It loads the embedding model named in the build manifest, so the first run on a
machine may download it. It never calls OpenAI or Supabase.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from web.services import build_registry
from web.services.search_engine import SearchEngine
from web.utils.config_loader import config, project_root

pytestmark = pytest.mark.integration

# The same path SearchEngine.__init__ resolves.
_PROCESSED_DATA_DIR = Path(project_root) / config.get(
    "paths", "processed_data", "web/processed_data"
)


@pytest.fixture(scope="module")
def engine() -> SearchEngine:
    if build_registry.read_active_build_id(_PROCESSED_DATA_DIR) is None:
        pytest.skip(
            f"no {build_registry.ACTIVE_BUILD_POINTER_NAME} under {_PROCESSED_DATA_DIR}; "
            "this machine has no active search build to load"
        )
    search_engine = SearchEngine()
    assert search_engine.initialize(), "the active build failed to load; see the log above"
    return search_engine


def test_the_active_build_loads_and_its_artifacts_agree(engine: SearchEngine) -> None:
    # initialize() runs the same row-count and manifest checks --preload does;
    # reaching here means they passed. Name the build so a failure log says which.
    assert engine.is_initialized()
    assert engine.active_build_id == build_registry.read_active_build_id(_PROCESSED_DATA_DIR)


# English only: an Arabic query is translated through OpenAI first
# (SearchEngine.search step 1), and this file must cost nothing to run.
@pytest.mark.parametrize(
    "query",
    ["pharmacovigilance reporting requirements", "drug registration requirements"],
)
def test_a_real_question_retrieves_real_chunks(engine: SearchEngine, query: str) -> None:
    results = engine.search(query)
    assert results, f"no results for {query!r} — retrieval returned nothing"
    for result in results:
        assert math.isfinite(result.score)
        assert result.document
