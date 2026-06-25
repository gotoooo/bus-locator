# -*- coding: utf-8 -*-
"""
事業者（プロバイダ）アダプタ層。

将来の多事業者対応に備え、フィードの「取得元」をここに集約する。
内部モデルは GTFS 標準なのでパーサ（gtfs_static / gtfs_realtime）は共通化でき、
プロバイダ差分は「URL の組み立て方」と「RT の有無」だけに閉じ込める。

新しい事業者を足したいときは PROVIDERS に Provider を1つ追加するだけでよい。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    agency_id: int
    name: str
    # 静的GTFS-JP
    static_current_url: str            # 当日有効
    static_future_url: str | None      # 改正予定（latest）。無ければ None
    # GTFS-RT（無い事業者は None）
    rt_trip_url: str | None
    rt_vehicle_url: str | None
    rt_alert_url: str | None
    has_realtime: bool = field(default=True)

    @property
    def rt_urls(self) -> dict[str, str | None]:
        return {
            "trip": self.rt_trip_url,
            "vehicle": self.rt_vehicle_url,
            "alert": self.rt_alert_url,
        }


def _mobusta(agency_id: int, name: str, base: str) -> Provider:
    """モバイルクリエイト基盤（ajt-mobusta-gtfs）共通の URL パターン。"""
    return Provider(
        agency_id=agency_id,
        name=name,
        static_current_url=f"{base}/static/{agency_id}/current_data.zip",
        static_future_url=f"{base}/static/{agency_id}/latest.zip",
        rt_trip_url=f"{base}/realtime/{agency_id}/trip_updates.bin",
        rt_vehicle_url=f"{base}/realtime/{agency_id}/vehicle_position.bin",
        rt_alert_url=f"{base}/realtime/{agency_id}/alerts.bin",
        has_realtime=True,
    )


_MOBUSTA_BASE = os.environ.get(
    "MOBUSTA_BASE", "https://ajt-mobusta-gtfs.mcapps.jp"
)

# 芸陽バス = id 11（広島県バス協会オープンデータ / モバイルクリエイト基盤, CC0）
GEIYO = _mobusta(11, "芸陽バス", _MOBUSTA_BASE)

PROVIDERS: dict[int, Provider] = {
    GEIYO.agency_id: GEIYO,
}

DEFAULT_AGENCY_ID = GEIYO.agency_id


def get_provider(agency_id: int) -> Provider:
    if agency_id not in PROVIDERS:
        raise KeyError(f"unknown agency_id: {agency_id}")
    return PROVIDERS[agency_id]
