# -*- coding: utf-8 -*-
"""
GTFS-RT（VehiclePosition / TripUpdate / Alert）のパース。

`geiyo_bus.py` の index_vehicles / index_trip_updates を移植・拡張。
Alert もインデックス化して運休・迂回表示に使えるようにした。
"""

from __future__ import annotations

from google.transit import gtfs_realtime_pb2 as pb


def parse_feed(content: bytes) -> pb.FeedMessage:
    feed = pb.FeedMessage()
    feed.ParseFromString(content)
    return feed


def index_vehicles(feed: pb.FeedMessage) -> dict:
    """trip_id -> {seq, lat, lon, status, ts, bearing, vehicle_id}"""
    out = {}
    for e in feed.entity:
        if not e.HasField("vehicle"):
            continue
        v = e.vehicle
        out[v.trip.trip_id] = {
            "seq": v.current_stop_sequence,
            "lat": v.position.latitude if v.HasField("position") else None,
            "lon": v.position.longitude if v.HasField("position") else None,
            "bearing": (v.position.bearing
                        if v.HasField("position") and v.position.HasField("bearing")
                        else None),
            "status": v.current_status,
            "ts": v.timestamp,
            "vehicle_id": v.vehicle.id if v.HasField("vehicle") else None,
        }
    return out


def index_trip_updates(feed: pb.FeedMessage) -> dict:
    """trip_id -> { stop_id -> {arr, delay, seq} }"""
    out = {}
    for e in feed.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        per_stop = {}
        for stu in tu.stop_time_update:
            arr = None
            delay = None
            # 発車基準に統一（時刻表が発車時刻のため）。departure を優先。
            if stu.HasField("departure"):
                if stu.departure.HasField("time"):
                    arr = stu.departure.time
                if stu.departure.HasField("delay"):
                    delay = stu.departure.delay
            # 発車情報が無ければ到着で代替
            if arr is None and stu.HasField("arrival"):
                if stu.arrival.HasField("time"):
                    arr = stu.arrival.time
                if delay is None and stu.arrival.HasField("delay"):
                    delay = stu.arrival.delay
            per_stop[stu.stop_id] = {
                "arr": arr,
                "delay": delay,
                "seq": stu.stop_sequence if stu.HasField("stop_sequence") else None,
            }
        out[tu.trip.trip_id] = per_stop
    return out


def index_alerts(feed: pb.FeedMessage) -> list[dict]:
    """運休・迂回などの Alert を、影響する trip_id / route_id / stop_id 付きで返す。"""
    out = []
    for e in feed.entity:
        if not e.HasField("alert"):
            continue
        al = e.alert

        def _txt(translated):
            for t in translated.translation:
                return t.text
            return ""

        informed = []
        for ie in al.informed_entity:
            informed.append({
                "trip_id": ie.trip.trip_id if ie.HasField("trip") else None,
                "route_id": ie.route_id or None,
                "stop_id": ie.stop_id or None,
                "agency_id": ie.agency_id or None,
            })
        out.append({
            "id": e.id,
            "cause": al.cause,
            "effect": al.effect,
            "header": _txt(al.header_text),
            "description": _txt(al.description_text),
            "informed": informed,
        })
    return out
