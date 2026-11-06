"""The Copilot's SQLite journal: matches, an index of GSI events, and recommendations.

Raw GSI stays in the recorder's ``.jsonl.gz`` files; this database only points into them (file name
and frame number), so nothing is stored twice. The schema moves forward with ``PRAGMA user_version``:
each entry of ``MIGRATIONS`` runs once, in order. Later stages add their tables as new entries.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from d2bg.copilot.models import CopilotEvent, GameContext, Recommendation, RecStatus

MIGRATIONS = [
    """
    CREATE TABLE matches (
        match_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        hero_id INTEGER,
        team TEXT,
        patch TEXT,
        first_seen_at REAL NOT NULL,
        last_seen_at REAL NOT NULL,
        first_game_time_s REAL,
        last_game_time_s REAL,
        recording TEXT
    );
    CREATE TABLE gsi_events_index (
        id INTEGER PRIMARY KEY,
        match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
        game_time_s REAL,
        created_at REAL NOT NULL,
        type TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        recording TEXT,
        frame INTEGER
    );
    CREATE UNIQUE INDEX gsi_events_once
        ON gsi_events_index(match_id, type, detail, IFNULL(game_time_s, -1e9));
    CREATE INDEX gsi_events_by_time ON gsi_events_index(match_id, game_time_s);
    CREATE TABLE recommendations (
        id TEXT PRIMARY KEY,
        match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
        game_time_s REAL,
        created_at REAL NOT NULL,
        type TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        alternatives TEXT NOT NULL,
        reason_ru TEXT NOT NULL,
        source TEXT NOT NULL,
        confidence REAL,
        confidence_kind TEXT NOT NULL,
        evidence_ids TEXT NOT NULL,
        context_hash TEXT NOT NULL,
        model_version TEXT NOT NULL,
        data_patch TEXT,
        status TEXT NOT NULL,
        expires_at REAL
    );
    CREATE INDEX recommendations_by_time ON recommendations(match_id, game_time_s);
    CREATE INDEX recommendations_by_type ON recommendations(type);
    CREATE INDEX recommendations_by_created ON recommendations(created_at);
    """,
    # 2: item groups (core, situational, defensive, buyback), stage 2.
    """
    ALTER TABLE recommendations ADD COLUMN category TEXT;
    CREATE INDEX recommendations_by_status ON recommendations(match_id, status);
    """,
    # 3: what the draft screen showed (d2bg-cv) and his corrections, stage 3. No foreign key: the
    # screen can be read before the first GSI event creates the match row.
    """
    CREATE TABLE draft_observations (
        id INTEGER PRIMARY KEY,
        match_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        game_time_s REAL,
        source TEXT NOT NULL,
        confidence REAL,
        unknown_slots INTEGER,
        data TEXT NOT NULL
    );
    CREATE INDEX draft_observations_by_match ON draft_observations(match_id, created_at);
    """,
]
_JSON_FIELDS = ("alternatives", "evidence_ids")


class CopilotStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        # One connection shared by the GSI handler and the replay thread, serialised by the lock.
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
                with self._db:
                    self._db.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")

    @property
    def version(self) -> int:
        with self._lock:
            return int(self._db.execute("PRAGMA user_version").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ── writes ─────────────────────────────────────────────────────

    def upsert_match(self, context: GameContext, source: str, now: float, recording: str | None) -> None:
        if not context.match_id:
            return
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO matches (match_id, source, hero_id, team, patch, first_seen_at, last_seen_at,
                       first_game_time_s, last_game_time_s, recording)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(match_id) DO UPDATE SET
                       last_seen_at = excluded.last_seen_at,
                       last_game_time_s = COALESCE(excluded.last_game_time_s, last_game_time_s),
                       hero_id = COALESCE(excluded.hero_id, hero_id),
                       team = COALESCE(excluded.team, team),
                       recording = COALESCE(recording, excluded.recording)""",
                (
                    context.match_id,
                    source,
                    context.hero_id,
                    context.team,
                    context.patch,
                    now,
                    now,
                    context.time_s,
                    context.time_s,
                    recording,
                ),
            )

    def add_events(
        self, events: list[CopilotEvent], now: float, recording: str | None, frame: int | None
    ) -> None:
        with self._lock, self._db:
            self._db.executemany(
                """INSERT OR IGNORE INTO gsi_events_index
                       (match_id, game_time_s, created_at, type, detail, recording, frame)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [(e.match_id, e.game_time_s, now, e.type, e.detail, recording, frame) for e in events],
            )

    def save_recommendation(self, rec: Recommendation, now: float) -> None:
        """Store ``rec``. The id is derived from the inputs, so replaying the same match stores nothing
        twice; a replayed recommendation becomes ``suggested`` again."""
        row = rec.model_dump()
        for name in _JSON_FIELDS:
            row[name] = json.dumps(row[name])
        row["created_at"] = now
        columns = ", ".join(row)
        with self._lock, self._db:
            self._db.execute(
                f"INSERT INTO recommendations ({columns}) VALUES ({', '.join('?' * len(row))}) "  # noqa: S608 - column names come from the model
                "ON CONFLICT(id) DO UPDATE SET status = excluded.status",
                tuple(row.values()),
            )

    def refresh_recommendation(self, rec_id: str, rec: Recommendation) -> None:
        """Same advice, new reasons (a part bought, a level gained): update the shown row in place."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE recommendations SET evidence_ids = ?, reason_ru = ?, alternatives = ?, confidence = ?, "
                "context_hash = ? WHERE id = ? AND status = 'suggested'",
                (
                    json.dumps(rec.evidence_ids),
                    rec.reason_ru,
                    json.dumps(rec.alternatives),
                    rec.confidence,
                    rec.context_hash,
                    rec_id,
                ),
            )

    def set_status(self, rec_id: str, status: RecStatus) -> bool:
        """Close a shown recommendation. Only a ``suggested`` one changes, so a dismissal sticks."""
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE recommendations SET status = ? WHERE id = ? AND status = 'suggested'",
                (status, rec_id),
            )
            return cur.rowcount > 0

    def add_draft_observation(
        self, match_id: str, now: float, game_time_s: float | None, source: str, data: dict[str, Any]
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO draft_observations
                       (match_id, created_at, game_time_s, source, confidence, unknown_slots, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    match_id,
                    now,
                    game_time_s,
                    source,
                    data.get("confidence"),
                    data.get("unknown_slots"),
                    json.dumps(data, separators=(",", ":")),
                ),
            )

    def expire_open(self) -> None:
        """Close every recommendation still shown. Only one match is live at a time."""
        with self._lock, self._db:
            self._db.execute("UPDATE recommendations SET status = 'expired' WHERE status = 'suggested'")

    # ── reads ──────────────────────────────────────────────────────

    def recommendations(
        self, match_id: str | None = None, limit: int = 50, status: RecStatus | None = None
    ) -> list[Recommendation]:
        where, args = [], []
        if match_id is not None:
            where.append("match_id = ?")
            args.append(match_id)
        if status is not None:
            where.append("status = ?")
            args.append(status)
        sql = "SELECT * FROM recommendations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY game_time_s DESC, created_at DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, limit)).fetchall()
        out = []
        for r in rows:
            data = {k: r[k] for k in r.keys() if k != "created_at"}  # noqa: SIM118 - sqlite3.Row has no __iter__ over keys
            for name in _JSON_FIELDS:
                data[name] = json.loads(data[name])
            out.append(Recommendation.model_validate(data))
        return out

    def events(self, match_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT game_time_s, type, detail, recording, frame FROM gsi_events_index "
                "WHERE match_id = ? ORDER BY id",
                (match_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                t: int(self._db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])  # noqa: S608 - fixed table names
                for t in ("matches", "gsi_events_index", "recommendations", "draft_observations")
            }
