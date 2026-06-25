# -*- coding: utf-8 -*-
"""
自前API（仕様書 §6）。

  GET  /health
  GET  /agencies
  GET  /stops?agencyId=&q=                バス停部分一致検索（登録UI用）
  GET  /stops/{stopId}/routes?agencyId=   その停留所の路線・方面（登録UI用）
  GET  /arrivals?agencyId=&stopId=&routeId=&directionId=   直近便
  GET  /alerts?agencyId=&routeId=&stopId= 運休・迂回 Alert

お気に入りはクライアント（PWA）側で端末ローカルに保持するため、
このバックエンドは状態を持たない（DB不要）。クライアントは登録停留所ごとに
/arrivals を呼ぶ。フィード直叩き禁止の制約は引き続きこのAPI経由で満たす。
"""

from __future__ import annotations

import time
import pathlib

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .providers import PROVIDERS, DEFAULT_AGENCY_ID
from .poller import DataManager
from .eta import find_arrivals

app = FastAPI(title="芸陽バス 接近情報API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

data = DataManager()

for _aid in PROVIDERS:
    data.add_agency(_aid)


@app.on_event("startup")
def _startup() -> None:
    if not settings.enable_poller:
        return
    try:
        data.bootstrap()      # 静的ロード（同期）
    except Exception as e:    # 起動時に取得できなくても API は立ち上げる
        app.state.bootstrap_error = str(e)
    data.start()              # RTポーリング開始


# ── メタ ────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    out = {"ok": True, "agencies": {}}
    for aid, st in data.agencies.items():
        out["agencies"][aid] = {
            "name": st.provider.name,
            "staticLoaded": st.static is not None,
            "staticStops": len(st.static.stops) if st.static else 0,
            "rtOk": st.rt_ok,
            "rtUpdatedAt": st.rt_updated_at,
            "vehicles": len(st.vehicles),
            "lastError": st.last_error,
        }
    return out


@app.get("/agencies")
def agencies() -> list:
    return [
        {"agencyId": p.agency_id, "name": p.name, "hasRealtime": p.has_realtime}
        for p in PROVIDERS.values()
    ]


# ── 登録UI: 検索・路線列挙 ────────────────────────────────
def _require_static(agency_id: int):
    st = data.get(agency_id)
    if st.static is None:
        raise HTTPException(503, "static GTFS not loaded yet")
    return st


@app.get("/stops")
def stops(q: str = Query("", description="バス停名キーワード"),
          agencyId: int = DEFAULT_AGENCY_ID,
          limit: int = 50) -> list:
    st = _require_static(agencyId)
    return st.static.search_stops(q, limit=limit)


@app.get("/stops/{stop_id}/routes")
def stop_routes(stop_id: str, agencyId: int = DEFAULT_AGENCY_ID) -> list:
    st = _require_static(agencyId)
    if stop_id not in st.static.stops:
        raise HTTPException(404, "unknown stopId")
    return st.static.routes_at_stop(stop_id)


# ── 直近便 ───────────────────────────────────────────────
def _arrivals(agency_id: int, stop_id: str,
              route_id: str | None, direction_id: str | None) -> dict:
    st = _require_static(agency_id)
    if stop_id not in st.static.stops:
        raise HTTPException(404, "unknown stopId")
    static, vehicles, trip_updates, rt_fresh = st.snapshot()
    result = find_arrivals(
        static, stop_id, time.time(), vehicles, trip_updates,
        route_id=route_id, direction_id=direction_id, rt_available=rt_fresh,
    )
    out = result.to_dict()
    out["agencyId"] = agency_id
    out["alerts"] = st.alerts_for(route_id=route_id, stop_id=stop_id)
    return out


@app.get("/arrivals")
def arrivals(stopId: str,
             agencyId: int = DEFAULT_AGENCY_ID,
             routeId: str | None = None,
             directionId: str | None = None) -> dict:
    return _arrivals(agencyId, stopId, routeId, directionId)


# ── Alert ────────────────────────────────────────────────
@app.get("/alerts")
def alerts(agencyId: int = DEFAULT_AGENCY_ID,
           routeId: str | None = None,
           stopId: str | None = None) -> list:
    st = data.get(agencyId)
    return st.alerts_for(route_id=routeId, stop_id=stopId)


# ── 静的Webクライアント配信（PWA / ローカル開発用）─────────
# 本番ではPWAをVercelに、APIをこのバックエンドに分離する想定だが、
# ローカル開発では同一オリジンでフロントも配れるよう、Vercelと同じ
# ルートパス（/app.js, /styles.css, /icons/*, /sw.js, /manifest.webmanifest）で配信する。
_WEB_DIR = pathlib.Path(__file__).resolve().parents[2] / "web"
if _WEB_DIR.is_dir():
    # Service Worker はルート配信が必須（スコープを "/" にするため）。
    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        return FileResponse(
            _WEB_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    @app.get("/manifest.webmanifest")
    def manifest() -> FileResponse:
        return FileResponse(
            _WEB_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    # 残り（/, /app.js, /styles.css, /config.js, /icons/*）を web/ から配信。
    # APIルートは上で登録済みのため、このマウントより優先される。
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
