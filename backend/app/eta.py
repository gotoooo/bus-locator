# -*- coding: utf-8 -*-
"""
コアロジック: 直近便・あと何駅・あと何分。

`geiyo_bus.py` の find_arrivals() をサービス化し、仕様書 §5/§8 を内包:
  - 運行サービスID判定（calendar + calendar_dates、24時超え便のため前日も候補）
  - ETA 3段フォールバック（予測 > 定刻+遅延 > 定刻）と source ラベル
  - あと何駅（VehiclePosition の current_stop_sequence 差）
  - 環状・循環路線（同一便が同じ stop を複数回通る）に対応
  - status: running / before_service / finished / no_realtime
  - 「まもなく到着」閾値（imminent）
  - trip_id 単位の重複排除
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict

from zoneinfo import ZoneInfo

from .gtfs_static import StaticGTFS
from .config import settings

# GTFS-JP の時刻は日本時間。サーバのタイムゾーン（Render等はUTC）に依存せず
# 必ず JST で epoch 化する。
JST = ZoneInfo("Asia/Tokyo")


def gtfs_time_to_epoch(s: str, service_date: dt.date) -> float:
    """GTFS時刻（"25:30:00" など24時超え対応）を epoch 秒へ。サービス日0時(JST)起点。"""
    h, m, sec = map(int, s.split(":"))
    base = dt.datetime.combine(service_date, dt.time(0, 0, 0), tzinfo=JST)
    return (base + dt.timedelta(hours=h, minutes=m, seconds=sec)).timestamp()


SRC_LABEL = {
    "predict": "リアルタイム予測",
    "delay": "定刻+遅延",
    "schedule": "定刻のみ",
}


@dataclass
class Arrival:
    trip_id: str
    route_id: str
    route: str
    headsign: str
    direction_id: str
    stops_away: int | None
    eta_minutes: float
    eta_epoch: float
    scheduled_epoch: float      # 正規（定刻）の到着時刻
    delay_sec: int | None       # 実際(予測) − 定刻。+遅れ / −早発。RT無しは None
    source: str                 # "predict" | "delay" | "schedule"
    source_label: str
    status: str                 # "running" | "no_realtime"
    imminent: bool
    has_position: bool
    vehicle_lat: float | None = None
    vehicle_lon: float | None = None
    vehicle_bearing: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["vehicle"] = (
            {"lat": self.vehicle_lat, "lon": self.vehicle_lon,
             "bearing": self.vehicle_bearing}
            if self.has_position else None
        )
        for k in ("vehicle_lat", "vehicle_lon", "vehicle_bearing"):
            d.pop(k, None)
        return d


@dataclass
class ArrivalsResult:
    """1停留所ぶんの応答。空のときも before_service / finished を表現できる。"""
    stop_id: str
    stop_name: str
    service_status: str         # "in_service" | "before_service" | "finished" | "no_service" | "no_realtime"
    rt_available: bool
    arrivals: list

    def to_dict(self) -> dict:
        return {
            "stopId": self.stop_id,
            "stopName": self.stop_name,
            "serviceStatus": self.service_status,
            "rtAvailable": self.rt_available,
            "arrivals": [a.to_dict() for a in self.arrivals],
        }


def _candidate_days(now_epoch: float) -> list[dt.date]:
    today = dt.datetime.fromtimestamp(now_epoch, JST).date()
    # 24時超え便を拾うため前日サービスも候補に入れる
    return [today, today - dt.timedelta(days=1)]


def find_arrivals(static: StaticGTFS, stop_id: str, now_epoch: float,
                  vehicles: dict, trip_updates: dict,
                  route_id: str | None = None,
                  direction_id: str | None = None,
                  horizon_min: int | None = None,
                  rt_available: bool = True) -> ArrivalsResult:
    """指定 stop_id に対する直近の便を eta 昇順で返す。"""
    horizon_min = horizon_min if horizon_min is not None else settings.arrivals_horizon_min
    grace = settings.passed_grace_sec
    imminent_sec = settings.imminent_threshold_min * 60

    stop = static.stops.get(stop_id)
    stop_name = stop["name"] if stop else stop_id

    # この停留所を通る便だけを見る（逆引きインデックスで高速化）
    relevant_trips = static.trips_by_stop.get(stop_id, set())

    results: list[Arrival] = []
    seen_trip_ids: set[str] = set()
    # 始発前/終バス後判定用: 当日この停留所に来る全予定時刻
    all_sched_today: list[float] = []
    today = dt.datetime.fromtimestamp(now_epoch, JST).date()

    for day in _candidate_days(now_epoch):
        services = static.active_services(day)
        for trip_id in relevant_trips:
            trip = static.trips.get(trip_id)
            if not trip or trip["service_id"] not in services:
                continue
            if route_id and trip["route_id"] != route_id:
                continue
            if direction_id is not None and trip["direction"] != direction_id:
                continue

            stimes = static.stop_times.get(trip_id, [])
            # 環状路線では同一 stop を複数回通るため「全ての出現」を見る
            occurrences = [s for s in stimes if s["stop_id"] == stop_id]
            for target in occurrences:
                sched = gtfs_time_to_epoch(target["arr"], day)
                if day == today:
                    all_sched_today.append(sched)

                # ── ETA決定（優先度: 予測 > 定刻+遅延 > 定刻）──
                su = trip_updates.get(trip_id, {}).get(stop_id, {})
                if su.get("arr"):
                    eta_epoch, source = float(su["arr"]), "predict"
                elif su.get("delay") is not None:
                    eta_epoch, source = sched + su["delay"], "delay"
                else:
                    eta_epoch, source = sched, "schedule"

                # 定刻との差（実際/予測 − 定刻）。RT根拠が無い schedule は不明。
                delay_sec = None if source == "schedule" else round(eta_epoch - sched)

                # 既に通過 or 遠すぎる便は除外
                if eta_epoch < now_epoch - grace:
                    continue
                if eta_epoch > now_epoch + horizon_min * 60:
                    continue

                # ── あと何駅 ──（環状対応: この出現 seq と車両 seq の差）
                veh = vehicles.get(trip_id)
                stops_away = None
                if veh and veh.get("seq"):
                    stops_away = target["seq"] - veh["seq"]
                    if stops_away < 0:
                        continue  # この出現はもう通過済み

                has_position = bool(veh and veh.get("lat") is not None)
                # RT根拠があるか（予測/遅延/位置のいずれか）
                has_rt = has_position or source in ("predict", "delay")
                status = "running" if has_rt else "no_realtime"

                # trip_id 単位の重複排除（最も早い出現を採用）
                if trip_id in seen_trip_ids:
                    continue
                seen_trip_ids.add(trip_id)

                results.append(Arrival(
                    trip_id=trip_id,
                    route_id=trip["route_id"],
                    route=static.routes.get(trip["route_id"], trip["route_id"]),
                    headsign=trip["headsign"],
                    direction_id=trip["direction"],
                    stops_away=stops_away,
                    eta_minutes=(eta_epoch - now_epoch) / 60,
                    eta_epoch=eta_epoch,
                    scheduled_epoch=sched,
                    delay_sec=delay_sec,
                    source=source,
                    source_label=SRC_LABEL[source],
                    status=status,
                    imminent=(eta_epoch - now_epoch) <= imminent_sec,
                    has_position=has_position,
                    vehicle_lat=veh["lat"] if has_position else None,
                    vehicle_lon=veh["lon"] if has_position else None,
                    vehicle_bearing=veh.get("bearing") if has_position else None,
                ))

    results.sort(key=lambda a: a.eta_minutes)

    service_status = _service_status(
        results, all_sched_today, now_epoch, rt_available
    )
    return ArrivalsResult(
        stop_id=stop_id,
        stop_name=stop_name,
        service_status=service_status,
        rt_available=rt_available,
        arrivals=results,
    )


def _service_status(results: list, all_sched_today: list[float],
                    now_epoch: float, rt_available: bool) -> str:
    """空応答時に始発前/終バス後/無運行を区別する。"""
    if results:
        return "in_service"
    if not all_sched_today:
        return "no_service"            # 当日この停留所に便が無い
    if now_epoch < min(all_sched_today):
        return "before_service"        # 始発前
    if now_epoch > max(all_sched_today):
        return "finished"              # 終バス後
    # 当日便はあるがホライズン内に該当なし
    return "no_realtime" if not rt_available else "in_service"
