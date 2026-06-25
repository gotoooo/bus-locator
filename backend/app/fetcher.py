# -*- coding: utf-8 -*-
"""
フィード取得アダプタ。

ライブ HTTP 取得に加え、ローカルファイル（フィクスチャ）からの読み込みに対応する。
ネットワーク制限環境（許可リスト方式で ajt-mobusta-gtfs.mcapps.jp に到達できない、
あるいは開発中に高頻度アクセスを避けたい場合）では、取得済みの .zip / .bin を
ローカル保存して使い回せる（仕様書 §11）。
"""

from __future__ import annotations

import requests

from .config import settings


class FetchError(RuntimeError):
    pass


def _read_local(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def fetch_bytes(url: str | None, fixture: str | None = None) -> bytes:
    """fixture があればローカルから、無ければ url から取得。"""
    if fixture:
        return _read_local(fixture)
    if not url:
        raise FetchError("no url and no fixture provided")
    try:
        r = requests.get(url, headers={"User-Agent": settings.user_agent}, timeout=20)
        r.raise_for_status()
        return r.content
    except requests.RequestException as e:
        raise FetchError(f"fetch failed for {url}: {e}") from e
