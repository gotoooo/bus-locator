# -*- coding: utf-8 -*-
"""
静的 GTFS-JP の取り込み。

`geiyo_bus.py` の `StaticGTFS` を移植・拡張したもの:
  - feed_info.txt（ダイヤ改正日判定）に対応
  - バス停名の部分一致検索
  - 路線・方面の列挙（登録UI用）
  - 始発/終バス判定のための補助
内部モデルは GTFS 標準。文字コードは UTF-8（BOM対策で utf-8-sig）。
"""

from __future__ import annotations

import io
import csv
import zipfile
import datetime as dt
from dataclasses import dataclass, field


@dataclass
class StaticGTFS:
    stops: dict = field(default_factory=dict)        # stop_id -> {name, lat, lon}
    trips: dict = field(default_factory=dict)        # trip_id -> {route_id, service_id, direction, headsign}
    stop_times: dict = field(default_factory=dict)   # trip_id -> [ {seq, stop_id, arr} ] (seq昇順)
    routes: dict = field(default_factory=dict)       # route_id -> name
    calendar: dict = field(default_factory=dict)     # service_id -> {days set, start, end}
    cal_dates: dict = field(default_factory=dict)    # (service_id, 'YYYYMMDD') -> 1(追加)/2(削除)
    feed_info: dict = field(default_factory=dict)    # {start, end, version, publisher}
    # 逆引きインデックス: stop_id -> set(trip_id)（ETA算出を高速化）
    trips_by_stop: dict = field(default_factory=dict)

    # ── 取り込み ───────────────────────────────────────────
    def load_zip(self, content: bytes) -> "StaticGTFS":
        zf = zipfile.ZipFile(io.BytesIO(content))

        def rows(name):
            if name not in zf.namelist():
                return
            text = zf.read(name).decode("utf-8-sig", errors="replace")
            yield from csv.DictReader(io.StringIO(text))

        for r in rows("stops.txt"):
            self.stops[r["stop_id"]] = {
                "name": r.get("stop_name", ""),
                "lat": float(r["stop_lat"]) if r.get("stop_lat") else None,
                "lon": float(r["stop_lon"]) if r.get("stop_lon") else None,
            }
        for r in rows("routes.txt"):
            self.routes[r["route_id"]] = (
                r.get("route_short_name") or r.get("route_long_name", "")
            )
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

        for r in rows("feed_info.txt"):
            # 改正日判定に使う。複数行は最後の行で上書き（通常1行）。
            self.feed_info = {
                "start": r.get("feed_start_date", ""),
                "end": r.get("feed_end_date", ""),
                "version": r.get("feed_version", ""),
                "publisher": r.get("feed_publisher_name", ""),
            }

        self._build_indexes()
        return self

    def _build_indexes(self) -> None:
        self.trips_by_stop = {}
        for trip_id, stimes in self.stop_times.items():
            for s in stimes:
                self.trips_by_stop.setdefault(s["stop_id"], set()).add(trip_id)

    # ── 運行日判定 ───────────────────────────────────────────
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

    # ── 検索・列挙（登録UI用）─────────────────────────────────
    def search_stops(self, keyword: str, limit: int = 50) -> list[dict]:
        kw = keyword.strip()
        out = []
        for sid, s in self.stops.items():
            if kw and kw in s["name"]:
                out.append({"stopId": sid, "name": s["name"],
                            "lat": s["lat"], "lon": s["lon"]})
                if len(out) >= limit:
                    break
        return out

    def routes_at_stop(self, stop_id: str) -> list[dict]:
        """その停留所を通る (routeId, route, directionId, headsign) の一覧（重複排除）。"""
        seen = {}
        for trip_id in self.trips_by_stop.get(stop_id, ()):
            t = self.trips.get(trip_id)
            if not t:
                continue
            key = (t["route_id"], t["direction"], t["headsign"])
            if key not in seen:
                seen[key] = {
                    "routeId": t["route_id"],
                    "route": self.routes.get(t["route_id"], t["route_id"]),
                    "directionId": t["direction"],
                    "headsign": t["headsign"],
                }
        return list(seen.values())

    # ── ダイヤ改正判定 ───────────────────────────────────────
    def covers_date(self, day: dt.date) -> bool:
        """feed_info の有効期間にこの日が含まれるか（current/latest 切替判定用）。"""
        if not self.feed_info:
            return True  # feed_info が無ければ判定不能。current を信頼。
        ymd = day.strftime("%Y%m%d")
        start = self.feed_info.get("start") or "00000000"
        end = self.feed_info.get("end") or "99999999"
        return start <= ymd <= end
