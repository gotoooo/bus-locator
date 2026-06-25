# -*- coding: utf-8 -*-
"""アプリ設定。環境変数で上書き可能。"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # RT は15秒更新。ポーリング間隔は 15 秒以上を厳守（高頻度アクセス禁止）。
    rt_poll_interval_sec: int = max(15, _int("RT_POLL_INTERVAL_SEC", 15))
    # 静的データの再取得間隔（既定 1 日）。
    static_refresh_interval_sec: int = _int("STATIC_REFRESH_INTERVAL_SEC", 24 * 3600)
    # 直近便を探す時間ホライズン（分）
    arrivals_horizon_min: int = _int("ARRIVALS_HORIZON_MIN", 90)
    # 「まもなく到着」に切り替える閾値（分）
    imminent_threshold_min: float = float(os.environ.get("IMMINENT_THRESHOLD_MIN", "1.0"))
    # 既に通過とみなす猶予（秒）
    passed_grace_sec: int = _int("PASSED_GRACE_SEC", 60)
    # User-Agent
    user_agent: str = os.environ.get("USER_AGENT", "geiyo-bus-watcher/1.0")
    # RT取得に失敗した状態が「古い」とみなされるまでの秒数（フォールバック判定）
    rt_stale_after_sec: int = _int("RT_STALE_AFTER_SEC", 90)
    # 開発用: ライブ取得の代わりにローカルファイルを使う（ネットワーク制限環境向け）
    #   例: STATIC_FIXTURE=/path/current_data.zip
    #       RT_VEHICLE_FIXTURE=/path/vehicle_position.bin など
    static_fixture: str | None = os.environ.get("STATIC_FIXTURE") or None
    rt_vehicle_fixture: str | None = os.environ.get("RT_VEHICLE_FIXTURE") or None
    rt_trip_fixture: str | None = os.environ.get("RT_TRIP_FIXTURE") or None
    rt_alert_fixture: str | None = os.environ.get("RT_ALERT_FIXTURE") or None
    # 起動時に RT ポーリングを始めるか（テスト時は False）
    enable_poller: bool = os.environ.get("ENABLE_POLLER", "1") not in ("0", "false", "False")


settings = Settings()
