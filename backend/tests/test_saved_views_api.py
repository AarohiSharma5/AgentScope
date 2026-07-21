"""API tests for saved analytics views (custom dashboards)."""


def test_create_list_and_delete_saved_view(client):
    resp = client.post("/api/saved-views", json={
        "name": "Last 7 days · gpt-4o",
        "config": {"days": 7, "model": "gpt-4o"},
    })
    assert resp.status_code == 201
    created = resp.get_json()
    assert created["name"] == "Last 7 days · gpt-4o"
    assert created["config"] == {"days": 7, "model": "gpt-4o"}
    view_id = created["id"]

    listed = client.get("/api/saved-views").get_json()["data"]
    assert any(v["id"] == view_id for v in listed)

    assert client.delete(f"/api/saved-views/{view_id}").status_code == 204
    assert client.delete(f"/api/saved-views/{view_id}").status_code == 404
    remaining = client.get("/api/saved-views").get_json()["data"]
    assert all(v["id"] != view_id for v in remaining)


def test_saved_view_validation(client):
    # Missing name.
    assert client.post("/api/saved-views", json={"config": {}}).status_code == 400
    # Non-object config.
    assert client.post("/api/saved-views", json={
        "name": "x", "config": ["not", "an", "object"]}).status_code == 400
    # Config is optional (defaults to empty object).
    ok = client.post("/api/saved-views", json={"name": "Defaults"})
    assert ok.status_code == 201
    assert ok.get_json()["config"] == {}
