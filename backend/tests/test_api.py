# -*- coding: utf-8 -*-
"""
API のスモークテスト。

ポーラ無効・フィクスチャ静的データを注入して、ネットワークなしで検証する。
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from conftest import zip_bytes
from test_static import build_zip


@pytest.fixture
def client(monkeypatch):
    # ポーラを止め、お気に入りDBを一時ファイルに
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db.close()
    monkeypatch.setenv("ENABLE_POLLER", "0")
    monkeypatch.setenv("DB_PATH", db.name)

    # config / main は環境変数を import 時に読むのでここで読み込む
    import importlib
    import app.config as config
    importlib.reload(config)
    import app.store as store
    importlib.reload(store)
    import app.main as main
    importlib.reload(main)

    # 静的データを手で注入
    from app.gtfs_static import StaticGTFS
    st = main.data.get(11)
    st.static = StaticGTFS().load_zip(build_zip())

    c = TestClient(main.app)
    yield c
    os.unlink(db.name)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_stops_search(client):
    r = client.get("/stops", params={"q": "西条"})
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_stop_routes(client):
    r = client.get("/stops/S_A/routes")
    assert r.status_code == 200
    assert r.json()[0]["headsign"] == "広島大学"


def test_favorite_crud(client):
    r = client.post("/favorites", json={"stopId": "S_A", "agencyId": 11})
    assert r.status_code == 200
    fid = r.json()["id"]

    r = client.get("/favorites")
    assert any(f["id"] == fid for f in r.json())

    r = client.delete(f"/favorites/{fid}")
    assert r.status_code == 200


def test_favorite_unknown_stop(client):
    r = client.post("/favorites", json={"stopId": "NOPE", "agencyId": 11})
    assert r.status_code == 404


def test_arrivals_shape(client):
    r = client.get("/arrivals", params={"stopId": "S_A"})
    assert r.status_code == 200
    body = r.json()
    assert body["stopId"] == "S_A"
    assert "serviceStatus" in body
    assert "arrivals" in body
    assert body["rtAvailable"] is False  # ポーラ無効なのでRTなし


def test_dashboard(client):
    client.post("/favorites", json={"stopId": "S_B", "agencyId": 11})
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert any(card["stopId"] == "S_B" for card in r.json())
