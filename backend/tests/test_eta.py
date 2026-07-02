# -*- coding: utf-8 -*-
"""ETAエンジン（find_arrivals）のテスト。仕様書 §5/§8 を網羅。"""

import datetime as dt

from app.eta import find_arrivals, find_commute, gtfs_time_to_epoch, JST
from conftest import make_static


def at(base_day, hh, mm, ss=0):
    """base_day の JST 時刻を epoch に（GTFS時刻はJST基準のため）。"""
    return dt.datetime.combine(
        base_day, dt.time(hh, mm, ss), tzinfo=JST).timestamp()


# ── 24時超え時刻 ─────────────────────────────────────────
def test_gtfs_time_to_epoch_overnight(base_day):
    e = gtfs_time_to_epoch("25:30:00", base_day)
    expect = dt.datetime.combine(base_day, dt.time(0, 0), tzinfo=JST) + dt.timedelta(hours=25, minutes=30)
    assert e == expect.timestamp()


# ── 3段フォールバック ────────────────────────────────────
def test_schedule_only(simple_static, base_day):
    now = at(base_day, 7, 50)  # 08:10 のB便まで20分
    res = find_arrivals(simple_static, "S_B", now, {}, {})
    assert res.service_status == "in_service"
    assert len(res.arrivals) == 1
    a = res.arrivals[0]
    assert a.source == "schedule"
    assert a.status == "no_realtime"
    assert round(a.eta_minutes) == 20
    assert a.stops_away is None  # 位置情報なし


def test_predict_overrides_schedule(simple_static, base_day):
    now = at(base_day, 7, 50)
    # B到着を 08:05 と予測（定刻08:10より早い）
    tu = {"T1": {"S_B": {"arr": at(base_day, 8, 5), "delay": None}}}
    res = find_arrivals(simple_static, "S_B", now, {}, tu)
    a = res.arrivals[0]
    assert a.source == "predict"
    assert a.status == "running"
    assert round(a.eta_minutes) == 15


def test_delay_only(simple_static, base_day):
    now = at(base_day, 7, 50)
    tu = {"T1": {"S_B": {"arr": None, "delay": 180}}}  # 3分遅れ
    res = find_arrivals(simple_static, "S_B", now, {}, tu)
    a = res.arrivals[0]
    assert a.source == "delay"
    assert round(a.eta_minutes) == 23  # 20 + 3


# ── 定刻との差（遅れ/早発）──────────────────────────────────
def test_delay_sec_from_prediction(simple_static, base_day):
    now = at(base_day, 7, 50)
    # 定刻08:10、予測08:13 → +180秒の遅れ
    tu = {"T1": {"S_B": {"arr": at(base_day, 8, 13), "delay": None}}}
    res = find_arrivals(simple_static, "S_B", now, {}, tu)
    a = res.arrivals[0]
    assert a.scheduled_epoch == at(base_day, 8, 10)
    assert a.delay_sec == 180


def test_delay_sec_early(simple_static, base_day):
    now = at(base_day, 7, 50)
    tu = {"T1": {"S_B": {"arr": None, "delay": -120}}}  # 2分早発
    res = find_arrivals(simple_static, "S_B", now, {}, tu)
    assert res.arrivals[0].delay_sec == -120


def test_delay_sec_none_without_rt(simple_static, base_day):
    now = at(base_day, 7, 50)
    res = find_arrivals(simple_static, "S_B", now, {}, {})
    a = res.arrivals[0]
    assert a.delay_sec is None
    assert a.scheduled_epoch == at(base_day, 8, 10)


# ── あと何駅 ─────────────────────────────────────────────
def test_stops_away(simple_static, base_day):
    now = at(base_day, 7, 50)
    vehicles = {"T1": {"seq": 1, "lat": 34.40, "lon": 132.74, "ts": now}}
    res = find_arrivals(simple_static, "S_C", now, vehicles, {})
    a = res.arrivals[0]
    assert a.stops_away == 2  # seq 3 - seq 1
    assert a.has_position is True
    assert a.vehicle_lat == 34.40


def test_already_passed_stop_excluded(simple_static, base_day):
    now = at(base_day, 7, 50)
    # 車両は seq 3（C）にいる → B はもう通過済み
    vehicles = {"T1": {"seq": 3, "lat": 34.42, "lon": 132.76, "ts": now}}
    res = find_arrivals(simple_static, "S_B", now, vehicles, {})
    assert res.arrivals == []


# ── 時間ホライズン・通過済み ──────────────────────────────
def test_passed_trip_excluded(simple_static, base_day):
    now = at(base_day, 8, 30)  # 全便通過後
    res = find_arrivals(simple_static, "S_B", now, {}, {})
    assert res.arrivals == []
    assert res.service_status == "finished"


def test_before_service(simple_static, base_day):
    now = at(base_day, 5, 0)  # 始発前
    res = find_arrivals(simple_static, "S_B", now, {}, {})
    assert res.arrivals == []
    assert res.service_status == "before_service"


def test_horizon_excludes_far(simple_static, base_day):
    now = at(base_day, 6, 0)  # 08:10 まで130分 > 既定90分
    res = find_arrivals(simple_static, "S_B", now, {}, {})
    assert res.arrivals == []
    assert res.service_status == "before_service"


# ── 運行日判定 ───────────────────────────────────────────
def test_not_running_on_weekend(simple_static):
    sunday = dt.date(2026, 6, 28)
    now = dt.datetime.combine(sunday, dt.time(7, 50), tzinfo=JST).timestamp()
    res = find_arrivals(simple_static, "S_B", now, {}, {})
    assert res.arrivals == []
    assert res.service_status == "no_service"


def test_calendar_dates_exception_removes_service(simple_static, base_day):
    # base_day を運休に
    simple_static.cal_dates[("WD", base_day.strftime("%Y%m%d"))] = 2
    now = at(base_day, 7, 50)
    res = find_arrivals(simple_static, "S_B", now, {}, {})
    assert res.arrivals == []


# ── route / direction フィルタ ────────────────────────────
def test_route_filter(simple_static, base_day):
    now = at(base_day, 7, 50)
    res = find_arrivals(simple_static, "S_B", now, {}, {}, route_id="R_OTHER")
    assert res.arrivals == []
    res2 = find_arrivals(simple_static, "S_B", now, {}, {}, route_id="R1")
    assert len(res2.arrivals) == 1


# ── 「まもなく到着」閾値 ─────────────────────────────────
def test_imminent_flag(simple_static, base_day):
    now = at(base_day, 8, 9, 40)  # B 08:10 まで20秒
    res = find_arrivals(simple_static, "S_B", now, {}, {})
    assert res.arrivals[0].imminent is True


# ── 24時超え便（前日サービス）─────────────────────────────
def test_overnight_trip_from_previous_day(base_day):
    """前日サービスの 25:10（=翌日01:10）便を、翌日0時台に拾えるか。"""
    stops = {"S_A": {"name": "A", "lat": 0, "lon": 0},
             "S_B": {"name": "B", "lat": 0, "lon": 0}}
    routes = {"R1": "深夜便"}
    trips = {"TN": {"route_id": "R1", "service_id": "WD",
                    "direction": "0", "headsign": "B方面"}}
    stop_times = {"TN": [
        {"seq": 1, "stop_id": "S_A", "arr": "25:00:00"},
        {"seq": 2, "stop_id": "S_B", "arr": "25:10:00"},
    ]}
    calendar = {"WD": {"days": {0, 1, 2, 3, 4}, "start": "20260101", "end": "20271231"}}
    g = make_static(stops, routes, trips, stop_times, calendar)
    # base_day は火曜。翌日水曜の 01:00 に評価 → 火曜サービスの 25:10 便
    wed = base_day + dt.timedelta(days=1)
    now = dt.datetime.combine(wed, dt.time(1, 0), tzinfo=JST).timestamp()
    res = find_arrivals(g, "S_B", now, {}, {})
    assert len(res.arrivals) == 1
    assert round(res.arrivals[0].eta_minutes) == 10


# ── 通勤（往復）──────────────────────────────────────────
def _commute_static():
    """往路便 TF(才の瀬→…→日下橋) と 復路便 TR(日下橋→…→才の瀬)。"""
    stops = {
        "SAI_1": {"name": "才の瀬橋", "lat": 34.40, "lon": 132.70},
        "MID":   {"name": "中間",     "lat": 34.41, "lon": 132.71},
        "KUSA_1": {"name": "日下橋",  "lat": 34.42, "lon": 132.72},
    }
    routes = {"R": "通勤線"}
    trips = {
        "TF": {"route_id": "R", "service_id": "WD", "direction": "0", "headsign": "日下橋方面"},
        "TR": {"route_id": "R", "service_id": "WD", "direction": "1", "headsign": "才の瀬方面"},
    }
    stop_times = {
        "TF": [
            {"seq": 1, "stop_id": "SAI_1", "arr": "08:00:00"},
            {"seq": 2, "stop_id": "MID",   "arr": "08:05:00"},
            {"seq": 3, "stop_id": "KUSA_1", "arr": "08:10:00"},
        ],
        "TR": [
            {"seq": 1, "stop_id": "KUSA_1", "arr": "18:00:00"},
            {"seq": 2, "stop_id": "MID",    "arr": "18:05:00"},
            {"seq": 3, "stop_id": "SAI_1",  "arr": "18:10:00"},
        ],
    }
    calendar = {"WD": {"days": {0, 1, 2, 3, 4}, "start": "20260101", "end": "20271231"}}
    return make_static(stops, routes, trips, stop_times, calendar)


def test_commute_outbound_picks_correct_trip_and_stop(base_day):
    g = _commute_static()
    now = at(base_day, 7, 50)  # 才の瀬 08:00 発の20分前
    res = find_commute(g, "才の瀬", "日下橋", now, {}, {})
    assert len(res.arrivals) == 1
    a = res.arrivals[0]
    assert a.trip_id == "TF"                 # 往路便のみ
    assert a.board_stop_id == "SAI_1"        # 乗車は才の瀬
    assert a.board_stop_name == "才の瀬橋"
    assert round(a.eta_minutes) == 10        # 08:00 まで


def test_commute_inbound_is_reverse(base_day):
    g = _commute_static()
    now = at(base_day, 17, 50)  # 日下橋 18:00 発の10分前
    res = find_commute(g, "日下橋", "才の瀬", now, {}, {})
    assert len(res.arrivals) == 1
    a = res.arrivals[0]
    assert a.trip_id == "TR"
    assert a.board_stop_id == "KUSA_1"
    assert round(a.eta_minutes) == 10


def test_commute_excludes_wrong_direction(base_day):
    g = _commute_static()
    # 朝に「日下橋→才の瀬」を見ても、復路便(18:00)は範囲外で空
    now = at(base_day, 7, 50)
    res = find_commute(g, "日下橋", "才の瀬", now, {}, {})
    assert res.arrivals == []


# ── 環状路線（同一stopを2回通る）──────────────────────────
def test_circular_route_two_occurrences(base_day):
    stops = {"S_A": {"name": "A", "lat": 0, "lon": 0},
             "S_B": {"name": "B", "lat": 0, "lon": 0}}
    routes = {"RC": "循環線"}
    trips = {"TC": {"route_id": "RC", "service_id": "WD",
                    "direction": "0", "headsign": "循環"}}
    # A(08:00) B(08:10) A(08:20) B(08:30) のように同じstopを2回
    stop_times = {"TC": [
        {"seq": 1, "stop_id": "S_A", "arr": "08:00:00"},
        {"seq": 2, "stop_id": "S_B", "arr": "08:10:00"},
        {"seq": 3, "stop_id": "S_A", "arr": "08:20:00"},
        {"seq": 4, "stop_id": "S_B", "arr": "08:30:00"},
    ]}
    calendar = {"WD": {"days": {0, 1, 2, 3, 4}, "start": "20260101", "end": "20271231"}}
    g = make_static(stops, routes, trips, stop_times, calendar)
    now = dt.datetime.combine(base_day, dt.time(8, 15), tzinfo=JST).timestamp()
    # 08:10 の出現は通過済み、08:30 の出現が直近
    res = find_arrivals(g, "S_B", now, {}, {})
    assert len(res.arrivals) == 1
    assert round(res.arrivals[0].eta_minutes) == 15  # 08:30 まで
