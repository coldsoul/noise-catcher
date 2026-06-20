"""SQLite time-series storage for noise samples.

Stores per-second Leq and Lpeak dB(A) measurements with WAL mode
for concurrent read access during continuous recording.
"""

import sqlite3


class NoiseDB:
    """Time-series database for noise measurements."""

    def __init__(self, db_path: str = "noise_catcher.db") -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

    def initialize(self) -> None:
        """Create tables if they don't exist. Idempotent."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS noise_samples (
                ts       REAL PRIMARY KEY,
                leq_db   REAL NOT NULL,
                lpeak_db REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS noise_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                start_ts   REAL NOT NULL,
                end_ts     REAL NOT NULL,
                max_db     REAL NOT NULL,
                duration_s REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_samples_ts
                ON noise_samples(ts);
        """)
        self.conn.commit()

    def insert_sample(self, timestamp: float, leq_db: float, lpeak_db: float) -> None:
        """Insert or replace a single noise sample."""
        self.conn.execute(
            "INSERT OR REPLACE INTO noise_samples (ts, leq_db, lpeak_db) VALUES (?, ?, ?)",
            (timestamp, leq_db, lpeak_db),
        )
        self.conn.commit()

    def insert_samples(self, samples: list[tuple[float, float, float]]) -> None:
        """Batch insert samples. Each tuple is (timestamp, leq_db, lpeak_db)."""
        self.conn.executemany(
            "INSERT OR REPLACE INTO noise_samples (ts, leq_db, lpeak_db) VALUES (?, ?, ?)",
            samples,
        )
        self.conn.commit()

    def query_range(self, start: float, end: float) -> list[tuple[float, float, float]]:
        """Return all samples with timestamp in [start, end]."""
        rows = self.conn.execute(
            "SELECT ts, leq_db, lpeak_db FROM noise_samples WHERE ts >= ? AND ts <= ? ORDER BY ts",
            (start, end),
        ).fetchall()
        return [(float(r[0]), float(r[1]), float(r[2])) for r in rows]

    def get_latest_timestamp(self) -> float | None:
        """Return the most recent sample timestamp, or None if empty."""
        row = self.conn.execute("SELECT MAX(ts) FROM noise_samples").fetchone()
        return float(row[0]) if row[0] is not None else None

    def count_samples(self) -> int:
        """Return total number of stored samples."""
        row = self.conn.execute("SELECT COUNT(*) FROM noise_samples").fetchone()
        return int(row[0])

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def vacuum(self) -> None:
        """Reclaim disk space after deletions."""
        self.conn.execute("VACUUM")
