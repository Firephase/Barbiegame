"""Test fixtures.

Every test runs against a temporary data directory and the offline fixture
search corpus, so the suite is deterministic and never touches the network.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def _environment(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("workspace-data")
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir / 'test.db'}"
    os.environ["FIXTURE_SEARCH"] = "1"
    os.environ["WEB_SEARCH_PROVIDERS"] = "fixture"
    os.environ["ACADEMIC_PROVIDERS"] = "none"
    os.environ["LLM_PROVIDER"] = "extractive"
    yield data_dir


@pytest.fixture(scope="session")
def corpus():
    from app.core.provenance import Author, Evidentiary, SourceKind
    from app.providers.search.fixture import make_source

    return [
        make_source(
            "Base editing reduces tumour burden in EGFR-mutant xenografts",
            "https://www.nature.com/articles/x1",
            "CRISPR base editing reduced tumour volume by 42% relative to control in "
            "EGFR-mutant lung cancer xenografts at day 21. Median survival was extended "
            "from 34 to 61 days.",
            kind=SourceKind.JOURNAL_ARTICLE,
            container_title="Nature Biotechnology",
            published=date(2024, 3, 1),
            doi="10.1038/s41587-024-00001-1",
            is_peer_reviewed=True,
            authors=[Author.parse("Jennifer A Doudna")],
            evidentiary=Evidentiary.PRIMARY,
            cited_by_count=140,
        ),
        make_source(
            "Off-target editing persists after base-editor optimisation",
            "https://www.biorxiv.org/content/x2",
            "Whole-genome sequencing detected off-target edits at three loci in treated "
            "animals. Current base editors do not achieve clinical-grade specificity.",
            kind=SourceKind.PREPRINT,
            container_title="bioRxiv",
            published=date(2025, 1, 15),
            is_peer_reviewed=False,
            authors=[Author.parse("Feng Zhang")],
            evidentiary=Evidentiary.PRIMARY,
        ),
    ]


@pytest.fixture()
def client(corpus):
    from fastapi.testclient import TestClient

    from app.core.registry import registry
    from app.main import app
    from app.providers import bootstrap

    bootstrap()
    registry.get("web_search", "fixture").load(corpus)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def project(client):
    return client.post(
        "/api/projects", json={"name": "Test project", "question": "Does it work?"}
    ).json()
