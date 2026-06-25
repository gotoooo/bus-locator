# -*- coding: utf-8 -*-
"""テスト用ヘルパ: 合成 GTFS を組み立てる（ネットワーク不要）。"""

import io
import csv
import zipfile
import datetime as dt

import pytest

from app.gtfs_static import StaticGTFS


def make_static(stops, routes, trips, stop_times, calendar, cal_dates=None,
                feed_info=None) -> StaticGTFS:
    """辞書から StaticGTFS を直接構築する。"""
    g = StaticGTFS()
    g.stops = {sid: dict(v) for sid, v in stops.items()}
    g.routes = dict(routes)
    g.trips = {tid: dict(v) for tid, v in trips.items()}
    for tid, lst in stop_times.items():
        g.stop_times[tid] = sorted(
            [dict(s) for s in lst], key=lambda x: x["seq"])
    g.calendar = {sid: dict(v) for sid, v in calendar.items()}
    g.cal_dates = dict(cal_dates or {})
    g.feed_info = dict(feed_info or {})
    g._build_indexes()
    return g


def zip_bytes(files: dict[str, list[dict]]) -> bytes:
    """{filename: [rows]} から GTFS zip バイト列を作る。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, rows in files.items():
            sio = io.StringIO()
            if rows:
                w = csv.DictWriter(sio, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            zf.writestr(name, sio.getvalue())
    return buf.getvalue()


@pytest.fixture
def base_day():
    # テスト基準日（火曜日）
    return dt.date(2026, 6, 23)


@pytest.fixture
def simple_static(base_day):
    """A→B→C を走る trip を1本。平日(月-金)運行。"""
    ymd_start, ymd_end = "20260101", "20271231"
    stops = {
        "S_A": {"name": "A停留所", "lat": 34.40, "lon": 132.74},
        "S_B": {"name": "B停留所", "lat": 34.41, "lon": 132.75},
        "S_C": {"name": "C停留所", "lat": 34.42, "lon": 132.76},
    }
    routes = {"R1": "1番線"}
    trips = {
        "T1": {"route_id": "R1", "service_id": "WD",
               "direction": "0", "headsign": "C方面"},
    }
    stop_times = {
        "T1": [
            {"seq": 1, "stop_id": "S_A", "arr": "08:00:00"},
            {"seq": 2, "stop_id": "S_B", "arr": "08:10:00"},
            {"seq": 3, "stop_id": "S_C", "arr": "08:20:00"},
        ],
    }
    calendar = {
        "WD": {"days": {0, 1, 2, 3, 4}, "start": ymd_start, "end": ymd_end},
    }
    return make_static(stops, routes, trips, stop_times, calendar)
