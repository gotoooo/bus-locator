#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
芸陽バス（広島県バス協会オープンデータ / モバイルクリエイト基盤 id=11）
  静的 GTFS-JP と GTFS-リアルタイムを取得し、
  指定バス停の「直近の便・あと何駅・あと何分」を算出する。

ライセンス: 元データは CC0。本スクリプトはご自由にどうぞ。
依存: pip install gtfs-realtime-bindings requests
注意: RTは15秒更新。ポーリングは15秒以上の間隔で。高頻度アクセスは禁止。

このファイルはコアロジックの「参照実装」。本番の構造化コードは backend/app/ にある。
"""

import io
import csv
import time
import zipfile
import datetime as dt
from dataclasses import dataclass, field

import requests
from google.transit import gtfs_realtime_pb2 as pb

# ─────────────────────────────────────────────
# 芸陽バス = id 11
AGENCY_ID = 11
BASE = "https://ajt-mobusta-gtfs.mcapps.jp"
STATIC_URL = f"{BASE}/static/{AGENCY_ID}/current_data.zip"   # 本日有効な静的データ
RT_TRIP_URL = f"{BASE}/realtime/{AGENCY_ID}/trip_updates.bin"
RT_VEHICLE_URL = f"{BASE}/realtime/{AGENCY_ID}/vehicle_position.bin"
RT_ALERT_URL = f"{BASE}/realtime/{AGENCY_ID}/alerts.bin"

UA = {"User-Agent": "geiyo-bus-watcher/1.0"}


# ─────────────────────────────────────────────
# 静的データ（GTFS-JP）
# ─────────────────────────────────────────────
@dataclass
class StaticGTFS:
    stops: dict = field(default_factory=dict)        # stop_id -> {name, lat, lon}
    trips: dict = field(default_factory=dict)        # trip_id -> {route_id, service_id, direction, headsign}
    stop_times: dict = field(default_factory=dict)   # trip_id -> [ {seq, stop_id, arr} ] (seq昇順)
    routes: dict = field(default_factory=dict)       # route_id -> name
    calendar: dict = field(default_factory=dict)     # service_id -> {weekday set, start, end}
    cal_dates: dict = field(default_factory=dict)    # (service_id, 'YYYYMMDD') -> 1(追加)/2(削除)

    def load_zip(self, content: bytes):
        zf = zipfile.ZipFile(io.BytesIO(content))

        def rows(name):
            if name not in zf.namelist():
                return
            # GTFS-JPはUTF-8。BOM対策に utf-8-sig
            text = zf.read(name).decode("utf-8-sig", errors="replace")
            yield from csv.DictReader(io.StringIO(text))

        for r in rows("stops.txt"):
            self.stops[r["stop_id"]] = {
                "name": r.get("stop_name", ""),
                "lat": float(r["stop_lat"]) if r.get("stop_lat") else None,
                "lon": float(r["stop_lon"]) if r.get("stop_lon") else None,
            }
        for r in rows("routes.txt"):
            self.routes[r["route_id"]] = r.get("route_short_name") or r.get("route_long_name", "")
        for r in rows("trips.txt"):
            self.trips[r["trip_id"]] = {
                "route_id": r["route_id"],
                "service_id": r["service_id"],
                "direction": r.get("direction_id", ""),
                "headsign": r.get("trip_headsign", ""),
            }
        for r in rows("stop_times.txt"):
            self.stop_times.setdefault(r["trip_id"], []).append({
                "seq": int(r["stop_sequence"]),
                "stop_id": r["stop_id"],
                "arr": r.get("arrival_time") or r.get("departure_time"),
            })
        for lst in self.stop_times.values():
            lst.sort(key=lambda x: x["seq"])

        WD = ["monday", "tuesday", "wednesday", "thursday",
              "friday", "saturday", "sunday"]
        for r in rows("calendar.txt"):
            self.calendar[r["service_id"]] = {
                "days": {i for i, d in enumerate(WD) if r.get(d) == "1"},
                "start": r.get("start_date", ""),
                "end": r.get("end_date", ""),
            }
        for r in rows("calendar_dates.txt"):
            self.cal_dates[(r["service_id"], r["date"])] = int(r["exception_type"])

    def active_services(self, day: dt.date) -> set:
        """その日に運行する service_id 集合（calendar + 例外日を反映）"""
        ymd = day.strftime("%Y%m%d")
        active = set()
        for sid, c in self.calendar.items():
            if c["start"] <= ymd <= c["end"] and day.weekday() in c["days"]:
                active.add(sid)
        for (sid, d), ex in self.cal_dates.items():
            if d == ymd:
                if ex == 1:
                    active.add(sid)       # 運行日として追加
                elif ex == 2:
                    active.discard(sid)   # 運休
        return active


# ─────────────────────────────────────────────
# 時刻ユーティリティ（24時超え "25:30:00" に対応）
# ─────────────────────────────────────────────
def gtfs_time_to_epoch(s: str, service_date: dt.date) -> float:
    h, m, sec = map(int, s.split(":"))
    base = dt.datetime.combine(service_date, dt.time(0, 0, 0))
    return (base + dt.timedelta(hours=h, minutes=m, seconds=sec)).timestamp()


# ─────────────────────────────────────────────
# リアルタイム取得
# ─────────────────────────────────────────────
def fetch_feed(url: str) -> pb.FeedMessage:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    feed = pb.FeedMessage()
    feed.ParseFromString(r.content)
    return feed


def index_vehicles(feed: pb.FeedMessage) -> dict:
    """trip_id -> {seq, lat, lon, status, ts}"""
    out = {}
    for e in feed.entity:
        if not e.HasField("vehicle"):
            continue
        v = e.vehicle
        out[v.trip.trip_id] = {
            "seq": v.current_stop_sequence,
            "lat": v.position.latitude if v.HasField("position") else None,
            "lon": v.position.longitude if v.HasField("position") else None,
            "status": v.current_status,
            "ts": v.timestamp,
        }
    return out


def index_trip_updates(feed: pb.FeedMessage) -> dict:
    """trip_id -> { stop_id -> {arr_epoch, delay} }"""
    out = {}
    for e in feed.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        per_stop = {}
        for stu in tu.stop_time_update:
            arr = None
            delay = None
            if stu.HasField("arrival"):
                if stu.arrival.HasField("time"):
                    arr = stu.arrival.time
                if stu.arrival.HasField("delay"):
                    delay = stu.arrival.delay
            per_stop[stu.stop_id] = {"arr": arr, "delay": delay}
        out[tu.trip.trip_id] = per_stop
    return out


# ─────────────────────────────────────────────
# 「直近の便・あと何駅・あと何分」算出
# ─────────────────────────────────────────────
@dataclass
class Arrival:
    trip_id: str
    route: str
    headsign: str
    direction: str
    stops_away: int | None
    eta_minutes: float | None
    source: str            # "predict" | "delay" | "schedule"
    has_position: bool
    vehicle_lat: float | None = None
    vehicle_lon: float | None = None


def find_arrivals(static: StaticGTFS, stop_id: str, now_epoch: float,
                  vehicles: dict, trip_updates: dict,
                  route_id: str | None = None,
                  horizon_min: int = 90) -> list:
    """指定 stop_id に対する直近の便を時刻順で返す。"""
    today = dt.date.fromtimestamp(now_epoch)
    # 24時超え便を拾うため前日サービスも候補に入れる
    candidate_days = [today, today - dt.timedelta(days=1)]
    results = []

    for day in candidate_days:
        services = static.active_services(day)
        for trip_id, stimes in static.stop_times.items():
            trip = static.trips.get(trip_id)
            if not trip or trip["service_id"] not in services:
                continue
            if route_id and trip["route_id"] != route_id:
                continue
            # この便がmy stopを通るか
            target = next((s for s in stimes if s["stop_id"] == stop_id), None)
            if not target:
                continue

            sched = gtfs_time_to_epoch(target["arr"], day)

            # ── ETA決定（優先度: 予測 > 定刻+遅延 > 定刻）──
            tu = trip_updates.get(trip_id, {})
            su = tu.get(stop_id, {})
            if su.get("arr"):
                eta_epoch, source = su["arr"], "predict"
            elif su.get("delay") is not None:
                eta_epoch, source = sched + su["delay"], "delay"
            else:
                eta_epoch, source = sched, "schedule"

            # 既に通過 or 遠すぎる便は除外
            if eta_epoch < now_epoch - 60:
                continue
            if eta_epoch > now_epoch + horizon_min * 60:
                continue

            # ── あと何駅 ──
            veh = vehicles.get(trip_id)
            stops_away = None
            if veh and veh["seq"]:
                stops_away = target["seq"] - veh["seq"]
                if stops_away < 0:
                    continue  # もう通過済み

            results.append(Arrival(
                trip_id=trip_id,
                route=static.routes.get(trip["route_id"], trip["route_id"]),
                headsign=trip["headsign"],
                direction=trip["direction"],
                stops_away=stops_away,
                eta_minutes=(eta_epoch - now_epoch) / 60,
                source=source,
                has_position=bool(veh and veh.get("lat")),
                vehicle_lat=veh["lat"] if veh else None,
                vehicle_lon=veh["lon"] if veh else None,
            ))

    results.sort(key=lambda a: a.eta_minutes)
    return results


# ─────────────────────────────────────────────
# デモ実行
# ─────────────────────────────────────────────
SRC_LABEL = {"predict": "リアルタイム予測", "delay": "定刻+遅延", "schedule": "定刻のみ"}


def main():
    import sys
    print("静的データ取得中 …", STATIC_URL)
    static = StaticGTFS()
    static.load_zip(requests.get(STATIC_URL, headers=UA, timeout=30).content)
    print(f"  停留所 {len(static.stops)} / 便 {len(static.trips)} / 路線 {len(static.routes)}")

    keyword = sys.argv[1] if len(sys.argv) > 1 else None
    if not keyword:
        # バス停名の一覧を少し見せる
        print("\n--- バス停名で検索してください。例: python geiyo_bus.py 西条駅 ---")
        for sid, s in list(static.stops.items())[:20]:
            print(f"  {sid}\t{s['name']}")
        return

    matches = [(sid, s) for sid, s in static.stops.items() if keyword in s["name"]]
    if not matches:
        print(f"『{keyword}』に一致する停留所がありません")
        return
    print(f"\n『{keyword}』に一致: {len(matches)}件 → 先頭を使用: "
          f"{matches[0][1]['name']} ({matches[0][0]})")
    stop_id = matches[0][0]

    print("リアルタイム取得中 …")
    vehicles = index_vehicles(fetch_feed(RT_VEHICLE_URL))
    trip_updates = index_trip_updates(fetch_feed(RT_TRIP_URL))
    print(f"  走行中車両 {len(vehicles)} / 予測のある便 {len(trip_updates)}")

    now = time.time()
    arrivals = find_arrivals(static, stop_id, now, vehicles, trip_updates)

    print(f"\n=== {matches[0][1]['name']} の直近の便 ===")
    if not arrivals:
        print("  直近90分以内に到着予定の便はありません")
    for a in arrivals[:5]:
        sa = f"あと{a.stops_away}駅" if a.stops_away is not None else "位置情報なし"
        pos = ""
        if a.has_position:
            pos = f" 〔現在地 {a.vehicle_lat:.5f},{a.vehicle_lon:.5f}〕"
        print(f"  [{a.route}] {a.headsign}方面 / {sa} / "
              f"約{a.eta_minutes:.0f}分 ({SRC_LABEL[a.source]}){pos}")


if __name__ == "__main__":
    main()
