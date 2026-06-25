#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ライブのフィードをローカルへ保存する（開発用スナップショット）。

ネットワークが芸陽バスのホストに到達できる環境で1回だけ実行し、
取得済みの .zip / .bin を使い回すことで「15秒以上の間隔・高頻度禁止」の
制約を守りつつオフライン開発できる（仕様書 §11）。

  python tools/snapshot_feeds.py ./snapshots
  STATIC_FIXTURE=./snapshots/current_data.zip \
  RT_VEHICLE_FIXTURE=./snapshots/vehicle_position.bin \
  RT_TRIP_FIXTURE=./snapshots/trip_updates.bin \
  RT_ALERT_FIXTURE=./snapshots/alerts.bin \
  uvicorn app.main:app
"""

import os
import sys
import pathlib

# app/ を import path に
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.providers import get_provider  # noqa: E402
from app.fetcher import fetch_bytes      # noqa: E402


def main(outdir: str, agency_id: int = 11):
    p = get_provider(agency_id)
    out = pathlib.Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    targets = {
        "current_data.zip": p.static_current_url,
        "vehicle_position.bin": p.rt_vehicle_url,
        "trip_updates.bin": p.rt_trip_url,
        "alerts.bin": p.rt_alert_url,
    }
    for name, url in targets.items():
        try:
            data = fetch_bytes(url)
            (out / name).write_bytes(data)
            print(f"  saved {name} ({len(data)} bytes)")
        except Exception as e:
            print(f"  FAILED {name}: {e}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "./snapshots")
