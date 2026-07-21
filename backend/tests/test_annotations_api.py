"""API tests for timeline annotations (deploy / change markers)."""


def test_create_list_and_delete_annotation(client):
    # Create with a bare ISO date.
    resp = client.post("/api/annotations", json={
        "label": "v2 prompt shipped",
        "annotated_at": "2026-07-20",
        "description": "Rewrote the system prompt.",
    })
    assert resp.status_code == 201
    created = resp.get_json()
    assert created["label"] == "v2 prompt shipped"
    assert created["date"] == "2026-07-20"
    assert created["description"] == "Rewrote the system prompt."
    annotation_id = created["id"]

    # It shows up in the list.
    listed = client.get("/api/annotations")
    assert listed.status_code == 200
    data = listed.get_json()["data"]
    assert any(a["id"] == annotation_id for a in data)

    # Delete removes it.
    deleted = client.delete(f"/api/annotations/{annotation_id}")
    assert deleted.status_code == 204
    assert client.delete(f"/api/annotations/{annotation_id}").status_code == 404
    remaining = client.get("/api/annotations").get_json()["data"]
    assert all(a["id"] != annotation_id for a in remaining)


def test_create_annotation_validation(client):
    # Missing label.
    assert client.post("/api/annotations", json={"annotated_at": "2026-07-20"}).status_code == 400
    # Missing / invalid date.
    assert client.post("/api/annotations", json={"label": "x"}).status_code == 400
    assert client.post(
        "/api/annotations", json={"label": "x", "annotated_at": "not-a-date"}
    ).status_code == 400
