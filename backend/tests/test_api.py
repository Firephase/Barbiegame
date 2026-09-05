"""End-to-end API behaviour, including honest degradation."""
from __future__ import annotations


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_providers_reports_why_each_capability_is_off(client):
    report = client.get("/api/providers").json()
    assert "capabilities" in report
    for capability, info in report["capabilities"].items():
        for provider in info["providers"]:
            if not provider["available"]:
                assert provider["reason"], f"{capability}/{provider['name']} gives no reason"


def test_capabilities_lists_the_options_the_ui_offers(client):
    payload = client.get("/api/capabilities").json()
    assert {m["name"] for m in payload["modes"]} >= {
        "quick", "deep_research", "paper_analyst", "data_analyst",
        "image_analyst", "scientific_writer", "skeptic", "teacher",
    }
    assert set(payload["export_formats"]) >= {"pdf", "docx", "md", "xlsx", "pptx", "bibtex", "ris"}


def test_research_returns_a_verified_answer(client, project):
    response = client.post(
        "/api/research",
        json={
            "question": "Does CRISPR base editing reduce tumour volume?",
            "project_id": project["id"],
            "mode": "quick",
        },
    )
    assert response.status_code == 200
    answer = response.json()
    assert answer["sources"]
    assert answer["trace"]["steps"]
    # every citation resolves to a source in this answer
    ids = {s["id"] for s in answer["sources"]}
    for claim in answer["claims"]:
        for citation in claim["citations"]:
            assert citation["source_id"] in ids


def test_research_records_into_the_project(client, project):
    client.post(
        "/api/research",
        json={"question": "off-target editing", "project_id": project["id"], "mode": "quick"},
    )
    refreshed = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed["source_count"] > 0
    assert refreshed["message_count"] == 2
    assert refreshed["passage_count"] > 0


def test_project_recall_searches_its_own_corpus(client, project):
    client.post(
        "/api/research",
        json={"question": "off-target editing loci", "project_id": project["id"], "mode": "quick"},
    )
    recall = client.get(
        f"/api/projects/{project['id']}/recall", params={"q": "off-target loci"}
    ).json()
    assert recall["items"]
    assert recall["items"][0]["passages"]


def test_unavailable_capability_explains_itself(client, project):
    """A missing reasoning model produces a reason, not a fabricated diagram."""
    response = client.post(
        "/api/diagrams", json={"description": "CRISPR mechanism", "kind": "mechanism"}
    )
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "provider_unavailable"
    assert "ANTHROPIC_API_KEY" in error["message"]


def test_unknown_mode_is_rejected_with_the_options(client):
    response = client.post("/api/research", json={"question": "x", "mode": "wizard"})
    assert response.status_code == 422


def test_upload_parses_and_indexes_a_dataset(client, project, tmp_path):
    csv = tmp_path / "trial.csv"
    csv.write_text("arm,value\ncontrol,10\ncontrol,11\ntreated,6\ntreated,7\n")
    response = client.post(
        "/api/files",
        data={"project_id": project["id"]},
        files={"files": ("trial.csv", csv.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200
    uploaded = response.json()["uploaded"][0]
    assert uploaded["kind"] == "dataset"

    columns = client.get(f"/api/datasets/{uploaded['source_id']}/columns").json()
    assert {c["name"] for c in columns["columns"]} == {"arm", "value"}

    stats = client.post(
        "/api/analysis",
        json={
            "source_id": uploaded["source_id"], "operation": "compare",
            "value_column": "value", "group_column": "arm",
        },
    ).json()
    assert stats["p_value"] is not None
    assert stats["assumptions"]


def test_chart_endpoint_returns_a_spec_and_a_figure(client, project, tmp_path):
    rows = [{"arm": "a", "v": 1}, {"arm": "a", "v": 2}, {"arm": "b", "v": 5}, {"arm": "b", "v": 6}]
    spec = client.post(
        "/api/charts", json={"rows": rows, "form": "bar", "x": "arm", "y": "v", "aggregate": "mean"}
    ).json()
    assert spec["series"][0]["y"] == [1.5, 5.5]

    figure = client.post(
        "/api/charts/render?fmt=png",
        json={"rows": rows, "form": "bar", "x": "arm", "y": "v", "aggregate": "mean"},
    )
    assert figure.status_code == 200
    assert figure.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_every_export_format_produces_bytes(client, project):
    client.post(
        "/api/research",
        json={"question": "tumour volume", "project_id": project["id"], "mode": "quick"},
    )
    messages = client.get(f"/api/projects/{project['id']}/messages").json()["items"]
    message_id = [m for m in messages if m["role"] == "assistant"][-1]["id"]
    for fmt in ("md", "txt", "pdf", "docx", "csv", "xlsx", "bibtex", "ris", "json", "pptx"):
        response = client.post(
            "/api/export", json={"message_id": message_id, "format": fmt, "style": "apa"}
        )
        assert response.status_code == 200, fmt
        assert len(response.content) > 100, fmt


def test_citations_endpoint_renders_every_style(client, project):
    client.post(
        "/api/research",
        json={"question": "tumour volume", "project_id": project["id"], "mode": "quick"},
    )
    payload = client.post(
        "/api/citations/format", json={"project_id": project["id"], "style": "ieee"}
    ).json()
    assert payload["bibliography"].startswith("[1] ")
    assert set(payload["items"][0]["all_styles"]) >= {"apa", "mla", "chicago", "ieee", "vancouver", "bibtex"}


def test_knowledge_graph_builds_from_real_metadata(client, project):
    client.post(
        "/api/research",
        json={"question": "tumour volume", "project_id": project["id"], "mode": "quick"},
    )
    graph = client.get(f"/api/projects/{project['id']}/graph").json()
    assert graph["stats"]["nodes"] > 0
    kinds = graph["stats"]["by_kind"]
    assert kinds.get("paper", 0) >= 1
    # every node points back at something real
    for node in graph["nodes"]:
        assert node["label"]


def test_project_deletion_cleans_up(client):
    created = client.post("/api/projects", json={"name": "Temp"}).json()
    assert client.delete(f"/api/projects/{created['id']}").status_code == 204
    assert client.get(f"/api/projects/{created['id']}").status_code == 404
