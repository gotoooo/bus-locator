# -*- coding: utf-8 -*-
"""
API のスモークテスト。

ポーラ無効・フィクスチャ静的データを注入して、ネットワークなしで検証する。
お気に入りはクライアント側（localStorage）が持つため、バックエンドは状態を持たない。
"""

import pytest
from fastapi.testclient import TestClient

from test_static import build_zip


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENABLE_POLLER", "0")

    # config / main は環境変数を import 時に読むのでここで読み込む
    import importlib
    import app.config as config
    importlib.reload(config)
    import app.main as main
    importlib.reload(main)

    # 静的データを手で注入
    from app.gtfs_static import StaticGTFS
    st = main.data.get(11)
    st.static = StaticGTFS().load_zip(build_zip())

    return TestClient(main.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_agencies(client):
    r = client.get("/agencies")
    assert r.status_code == 200
    assert any(a["agencyId"] == 11 for a in r.json())


def test_stops_search(client):
    r = client.get("/stops", params={"q": "西条"})
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_stop_routes(client):
    r = client.get("/stops/S_A/routes")
    assert r.status_code == 200
    assert r.json()[0]["headsign"] == "広島大学"


def test_arrivals_shape(client):
    r = client.get("/arrivals", params={"stopId": "S_A"})
    assert r.status_code == 200
    body = r.json()
    assert body["stopId"] == "S_A"
    assert "serviceStatus" in body
    assert "arrivals" in body
    assert body["rtAvailable"] is False  # ポーラ無効なのでRTなし


def test_arrivals_unknown_stop(client):
    r = client.get("/arrivals", params={"stopId": "NOPE"})
    assert r.status_code == 404


def test_arrivals_route_filter(client):
    # routeId で絞れる（存在しない路線なら空）
    r = client.get("/arrivals", params={"stopId": "S_A", "routeId": "NOPE"})
    assert r.status_code == 200
    assert r.json()["arrivals"] == []


def test_commute_endpoint(client):
    # build_zip: T1 は S_A(08:00)→S_B(08:05)→S_C(08:20)。西条→広島大学 方向。
    r = client.get("/commute", params={"from": "西条駅", "to": "広島大学"})
    assert r.status_code == 200
    body = r.json()
    assert body["from"] == "西条駅"
    assert "arrivals" in body and "serviceStatus" in body


def test_no_favorites_endpoint(client):
    # お気に入りはサーバに無い（クライアント保持）
    assert client.get("/favorites").status_code == 404
    assert client.get("/dashboard").status_code == 404
