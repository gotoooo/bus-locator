# -*- coding: utf-8 -*-
"""静的GTFS取り込み・検索のテスト。"""

import datetime as dt

from app.gtfs_static import StaticGTFS
from conftest import zip_bytes


def build_zip():
    return zip_bytes({
        "stops.txt": [
            {"stop_id": "S_A", "stop_name": "西条駅", "stop_lat": "34.42", "stop_lon": "132.74"},
            {"stop_id": "S_B", "stop_name": "西条中央", "stop_lat": "34.43", "stop_lon": "132.75"},
            {"stop_id": "S_C", "stop_name": "広島大学", "stop_lat": "34.40", "stop_lon": "132.71"},
        ],
        "routes.txt": [
            {"route_id": "R1", "route_short_name": "1", "route_long_name": "西条線"},
        ],
        "trips.txt": [
            {"route_id": "R1", "service_id": "WD", "trip_id": "T1",
             "trip_headsign": "広島大学", "direction_id": "0"},
        ],
        "stop_times.txt": [
            {"trip_id": "T1", "stop_sequence": "1", "stop_id": "S_A", "arrival_time": "08:00:00", "departure_time": "08:00:00"},
            {"trip_id": "T1", "stop_sequence": "2", "stop_id": "S_B", "arrival_time": "08:05:00", "departure_time": "08:05:00"},
            {"trip_id": "T1", "stop_sequence": "3", "stop_id": "S_C", "arrival_time": "08:20:00", "departure_time": "08:20:00"},
        ],
        "calendar.txt": [
            {"service_id": "WD", "monday": "1", "tuesday": "1", "wednesday": "1",
             "thursday": "1", "friday": "1", "saturday": "0", "sunday": "0",
             "start_date": "20260101", "end_date": "20271231"},
        ],
        "calendar_dates.txt": [
            {"service_id": "WD", "date": "20260623", "exception_type": "2"},  # 運休日
        ],
        "feed_info.txt": [
            {"feed_publisher_name": "広島県バス協会", "feed_version": "test",
             "feed_start_date": "20260101", "feed_end_date": "20271231"},
        ],
    })


def test_load_zip_counts():
    g = StaticGTFS().load_zip(build_zip())
    assert len(g.stops) == 3
    assert len(g.routes) == 1
    assert len(g.trips) == 1
    assert len(g.stop_times["T1"]) == 3
    assert g.feed_info["publisher"] == "広島県バス協会"


def test_stop_times_sorted():
    g = StaticGTFS().load_zip(build_zip())
    seqs = [s["seq"] for s in g.stop_times["T1"]]
    assert seqs == sorted(seqs)


def test_search_stops():
    g = StaticGTFS().load_zip(build_zip())
    hits = g.search_stops("西条")
    names = {h["name"] for h in hits}
    assert names == {"西条駅", "西条中央"}


def test_routes_at_stop():
    g = StaticGTFS().load_zip(build_zip())
    routes = g.routes_at_stop("S_A")
    assert len(routes) == 1
    assert routes[0]["headsign"] == "広島大学"
    assert routes[0]["directionId"] == "0"


def test_active_services_weekday():
    g = StaticGTFS().load_zip(build_zip())
    # 2026-06-24 は水曜（運休例外なし）→ 運行
    assert "WD" in g.active_services(dt.date(2026, 6, 24))
    # 2026-06-23 は火曜だが calendar_dates で運休
    assert "WD" not in g.active_services(dt.date(2026, 6, 23))
    # 2026-06-28 は日曜 → 運休
    assert "WD" not in g.active_services(dt.date(2026, 6, 28))


def test_covers_date():
    g = StaticGTFS().load_zip(build_zip())
    assert g.covers_date(dt.date(2026, 6, 24)) is True
    assert g.covers_date(dt.date(2030, 1, 1)) is False


def test_trips_by_stop_index():
    g = StaticGTFS().load_zip(build_zip())
    assert g.trips_by_stop["S_A"] == {"T1"}
    assert g.trips_by_stop["S_C"] == {"T1"}
