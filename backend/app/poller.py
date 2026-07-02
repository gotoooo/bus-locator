# -*- coding: utf-8 -*-
"""
バックエンド集約型のデータ層（仕様書 §3）。

  - 静的GTFS: 起動時 + 1日1回取得して保持
  - 動的RT  : 15秒間隔でポーリングし、メモリにキャッシュ。
              全クライアントへはこの1ソースから配る（クライアント直叩き禁止）。
  - RT欠損時は定刻案内へ自動フォールバック（rt_available=False）。

スレッドで動く軽量ポーラ。Redis 等への置き換えは AgencyState の口を保てば容易。
"""

from __future__ import annotations

import time
import threading
import datetime as dt

from .config import settings
from .providers import Provider, get_provider
from .gtfs_static import StaticGTFS
from .gtfs_realtime import parse_feed, index_vehicles, index_trip_updates, index_alerts
from .fetcher import fetch_bytes, FetchError


class AgencyState:
    """1事業者ぶんの静的データ + RTキャッシュ。スレッドセーフに読める。"""

    def __init__(self, provider: Provider):
        self.provider = provider
        self._lock = threading.RLock()
        self.static: StaticGTFS | None = None
        self.static_loaded_at: float = 0.0
        self.vehicles: dict = {}
        self.trip_updates: dict = {}
        self.alerts: list = []
        self.rt_diag: dict = {}
        self.rt_updated_at: float = 0.0
        self.rt_ok: bool = False
        self.last_error: str | None = None

    # ── 静的 ─────────────────────────────────────────────
    def load_static(self) -> None:
        p = self.provider
        # 改正日対応: current が今日をカバーしなければ latest を試す
        content = fetch_bytes(p.static_current_url, settings.static_fixture)
        g = StaticGTFS().load_zip(content)
        from .eta import JST
        today = dt.datetime.now(JST).date()
        if not g.covers_date(today) and p.static_future_url and not settings.static_fixture:
            try:
                future = StaticGTFS().load_zip(fetch_bytes(p.static_future_url))
                if future.covers_date(today):
                    g = future
            except FetchError:
                pass  # latest 取得失敗時は current を使う
        with self._lock:
            self.static = g
            self.static_loaded_at = time.time()

    # ── 動的 ─────────────────────────────────────────────
    def poll_rt(self) -> None:
        p = self.provider
        if not p.has_realtime:
            return
        try:
            vfeed = parse_feed(fetch_bytes(p.rt_vehicle_url, settings.rt_vehicle_fixture))
            tfeed = parse_feed(fetch_bytes(p.rt_trip_url, settings.rt_trip_fixture))
            veh = index_vehicles(vfeed)
            tu = index_trip_updates(tfeed)
            diag = self._rt_diagnostics(vfeed, tfeed)
            alerts = []
            try:
                alerts = index_alerts(parse_feed(
                    fetch_bytes(p.rt_alert_url, settings.rt_alert_fixture)))
            except FetchError:
                pass  # Alert は欠けても致命的でない
            with self._lock:
                self.vehicles = veh
                self.trip_updates = tu
                self.alerts = alerts
                self.rt_diag = diag
                self.rt_updated_at = time.time()
                self.rt_ok = True
                self.last_error = None
        except (FetchError, Exception) as e:  # RT欠損 → フォールバック
            with self._lock:
                self.rt_ok = False
                self.last_error = str(e)

    @staticmethod
    def _rt_diagnostics(vfeed, tfeed) -> dict:
        """車両位置と便のtrip_id対応を診断する（「位置情報なし」の原因切り分け用）。"""
        v_ids = [e.vehicle.trip.trip_id for e in vfeed.entity if e.HasField("vehicle")]
        t_ids = [e.trip_update.trip.trip_id for e in tfeed.entity if e.HasField("trip_update")]
        return {
            "vehicleEntities": len(v_ids),
            "vehicleWithTripId": sum(1 for x in v_ids if x),
            "sampleVehicleTripIds": [x for x in v_ids if x][:8],
            "tripUpdateEntities": len(t_ids),
            "sampleTripUpdateTripIds": [x for x in t_ids if x][:8],
        }

    # ── 読み取り（ETA算出用スナップショット）──────────────
    def snapshot(self):
        with self._lock:
            rt_fresh = (
                self.rt_ok
                and (time.time() - self.rt_updated_at) <= settings.rt_stale_after_sec
            )
            return self.static, dict(self.vehicles), dict(self.trip_updates), rt_fresh

    def alerts_for(self, route_id=None, stop_id=None, trip_id=None) -> list:
        with self._lock:
            alerts = list(self.alerts)
        if route_id is None and stop_id is None and trip_id is None:
            return alerts
        out = []
        for a in alerts:
            for ie in a["informed"]:
                if route_id and ie["route_id"] == route_id:
                    out.append(a); break
                if stop_id and ie["stop_id"] == stop_id:
                    out.append(a); break
                if trip_id and ie["trip_id"] == trip_id:
                    out.append(a); break
        return out


class DataManager:
    """全事業者ぶんの AgencyState を束ね、バックグラウンドでポーリングする。"""

    def __init__(self):
        self.agencies: dict[int, AgencyState] = {}
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def add_agency(self, agency_id: int) -> AgencyState:
        st = AgencyState(get_provider(agency_id))
        self.agencies[agency_id] = st
        return st

    def get(self, agency_id: int) -> AgencyState:
        if agency_id not in self.agencies:
            self.add_agency(agency_id)
        return self.agencies[agency_id]

    def bootstrap(self) -> None:
        """起動時の静的ロード（同期）。"""
        for st in self.agencies.values():
            st.load_static()

    def start(self) -> None:
        """RTポーリング + 静的定期更新スレッドを開始。"""
        t_rt = threading.Thread(target=self._rt_loop, daemon=True, name="rt-poller")
        t_static = threading.Thread(target=self._static_loop, daemon=True, name="static-refresh")
        t_rt.start(); t_static.start()
        self._threads += [t_rt, t_static]

    def stop(self) -> None:
        self._stop.set()

    def _rt_loop(self) -> None:
        # 起動直後に1回
        for st in self.agencies.values():
            st.poll_rt()
        while not self._stop.wait(settings.rt_poll_interval_sec):
            for st in self.agencies.values():
                st.poll_rt()

    def _static_loop(self) -> None:
        while not self._stop.wait(settings.static_refresh_interval_sec):
            for st in self.agencies.values():
                try:
                    st.load_static()
                except FetchError:
                    pass
