"""Flask 5 接口(test client,身份/DB 用桩）。"""
import json

import pytest

from big_data_model.review.app import create_app


@pytest.fixture
def client(cases_file):
    app = create_app(cases_path=cases_file)
    app.config.update(TESTING=True)
    return app.test_client()


def test_get_cases(client):
    r = client.get("/api/review/cases")
    assert r.status_code == 200
    ids = {c["event_id"] for c in r.get_json()}
    assert {"P0-1", "P2-1", "OK-1", "P1-1"} <= ids


def test_get_meta(client):
    r = client.get("/api/review/meta").get_json()
    codes = {c["code"] for c in r["categories"]}
    assert "DB" in codes and "UNKNOWN" in codes
    assert "车险核保系统" in r["systems"]


def test_save_edit_and_reflect(client):
    r = client.post("/api/review/case/P0-1", json={"patch": {"类别": "DB"}, "base_version": None})
    assert r.status_code == 200
    v = r.get_json()["version"]
    d = {c["event_id"]: c for c in client.get("/api/review/cases").get_json()}["P0-1"]
    assert d["类别"]["value"] == "DB" and d["review"]["version"] == v


def test_stale_base_version_conflicts(client):
    client.post("/api/review/case/P0-1", json={"patch": {"类别": "DB"}, "base_version": None})
    r = client.post("/api/review/case/P0-1", json={"patch": {"类别": "APP"}, "base_version": None})
    assert r.status_code == 409 and r.get_json()["error"] == "version_conflict"


def test_invalid_patch_rejected(client):
    r = client.post("/api/review/case/P0-1", json={"patch": {"类别": "瞎写"}, "base_version": None})
    assert r.status_code == 400


def test_export_download(client):
    client.post("/api/review/case/P0-1", json={"patch": {"类别": "DB"}, "base_version": None})
    r = client.get("/api/review/export")
    assert r.status_code == 200
    merged = {json.loads(l)["事件ID"]: json.loads(l) for l in r.get_data(as_text=True).splitlines()}
    assert merged["P0-1"]["回填"]["类别"] == "DB"


def test_vocab_pending(client):
    r = client.post("/api/vocab/pending", json={"system_name": "某新系统", "source_event_id": "P1-1"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    r2 = client.post("/api/vocab/pending", json={"system_name": ""})
    assert r2.status_code == 400
