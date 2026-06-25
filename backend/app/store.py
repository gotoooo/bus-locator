# -*- coding: utf-8 -*-
"""
お気に入り（登録停留所）の永続化。

登録単位は仕様書 §4 のとおり agencyId + stopId + routeId + directionId。
routeId / directionId は任意（その停留所の全便を見たい場合は空）。
軽量に SQLite を使う。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass

from .config import settings


@dataclass
class Favorite:
    id: int
    user_id: str
    agency_id: int
    stop_id: str
    route_id: str | None
    direction_id: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "agencyId": self.agency_id,
            "stopId": self.stop_id,
            "routeId": self.route_id,
            "directionId": self.direction_id,
        }


class FavoriteStore:
    def __init__(self, path: str | None = None):
        self.path = path or settings.db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      TEXT NOT NULL DEFAULT 'default',
                    agency_id    INTEGER NOT NULL,
                    stop_id      TEXT NOT NULL,
                    route_id     TEXT,
                    direction_id TEXT,
                    UNIQUE(user_id, agency_id, stop_id, route_id, direction_id)
                )
            """)
            self._conn.commit()

    def add(self, agency_id: int, stop_id: str,
            route_id: str | None = None, direction_id: str | None = None,
            user_id: str = "default") -> Favorite:
        with self._lock:
            cur = self._conn.execute(
                """INSERT OR IGNORE INTO favorites
                   (user_id, agency_id, stop_id, route_id, direction_id)
                   VALUES (?,?,?,?,?)""",
                (user_id, agency_id, stop_id, route_id, direction_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                """SELECT * FROM favorites WHERE user_id=? AND agency_id=?
                   AND stop_id=? AND IFNULL(route_id,'')=IFNULL(?,'')
                   AND IFNULL(direction_id,'')=IFNULL(?,'')""",
                (user_id, agency_id, stop_id, route_id, direction_id),
            ).fetchone()
        return self._row(row)

    def list(self, user_id: str = "default") -> list[Favorite]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM favorites WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def delete(self, fav_id: int, user_id: str = "default") -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM favorites WHERE id=? AND user_id=?",
                (fav_id, user_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _row(row: sqlite3.Row) -> Favorite:
        return Favorite(
            id=row["id"],
            user_id=row["user_id"],
            agency_id=row["agency_id"],
            stop_id=row["stop_id"],
            route_id=row["route_id"] or None,
            direction_id=row["direction_id"] or None,
        )
