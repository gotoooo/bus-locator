#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
オフライン開発用の「デモ静的GTFS zip」を生成する。

ライブのフィードホスト (ajt-mobusta-gtfs.mcapps.jp) に到達できない環境でも
バックエンド/フロントを一通り動かせるよう、最小限の合成 GTFS を作る。

  python tools/make_demo_fixture.py demo_static.zip
  STATIC_FIXTURE=$PWD/demo_static.zip ENABLE_POLLER=1 uvicorn app.main:app
"""

import io
import csv
import sys
import zipfile
import datetime as dt


def _csv(rows):
    sio = io.StringIO()
    if rows:
        w = csv.DictWriter(sio, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return sio.getvalue()


def build(path: str):
    today = dt.date.today()
    start = (today - dt.timedelta(days=30)).strftime("%Y%m%d")
    end = (today + dt.timedelta(days=365)).strftime("%Y%m%d")

    stops = [
        {"stop_id": "1001", "stop_name": "西条駅", "stop_lat": "34.4189", "stop_lon": "132.7411"},
        {"stop_id": "1002", "stop_name": "西条中央", "stop_lat": "34.4250", "stop_lon": "132.7460"},
        {"stop_id": "1003", "stop_name": "広島大学", "stop_lat": "34.4030", "stop_lon": "132.7140"},
        {"stop_id": "1004", "stop_name": "八本松駅", "stop_lat": "34.4090", "stop_lon": "132.7790"},
    ]
    routes = [
        {"route_id": "R1", "route_short_name": "1", "route_long_name": "西条・広大線"},
        {"route_id": "R2", "route_short_name": "2", "route_long_name": "八本松線"},
    ]
    # 毎時 :00 と :30 に出る便を当日ぶん生成（デモなので時刻だけ）
    trips, stop_times = [], []
    for hh in range(6, 22):
        for mm in (0, 30):
            tid = f"T_{hh:02d}{mm:02d}"
            trips.append({"route_id": "R1", "service_id": "EVERYDAY",
                          "trip_id": tid, "trip_headsign": "広島大学", "direction_id": "0"})
            base = dt.timedelta(hours=hh, minutes=mm)
            for i, sid in enumerate(["1001", "1002", "1003"]):
                t = base + dt.timedelta(minutes=i * 8)
                hms = f"{t.seconds // 3600:02d}:{(t.seconds % 3600) // 60:02d}:00"
                stop_times.append({"trip_id": tid, "stop_sequence": str(i + 1),
                                   "stop_id": sid, "arrival_time": hms, "departure_time": hms})
    calendar = [{"service_id": "EVERYDAY", "monday": "1", "tuesday": "1",
                 "wednesday": "1", "thursday": "1", "friday": "1",
                 "saturday": "1", "sunday": "1", "start_date": start, "end_date": end}]
    feed_info = [{"feed_publisher_name": "DEMO", "feed_publisher_url": "http://example.com",
                  "feed_lang": "ja", "feed_version": "demo",
                  "feed_start_date": start, "feed_end_date": end}]

    files = {
        "stops.txt": stops, "routes.txt": routes, "trips.txt": trips,
        "stop_times.txt": stop_times, "calendar.txt": calendar,
        "calendar_dates.txt": [], "feed_info.txt": feed_info,
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, rows in files.items():
            zf.writestr(name, _csv(rows))
    print(f"wrote {path} ({len(trips)} trips, {len(stops)} stops)")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "demo_static.zip")
