"""Tests for the SQLite time-series storage layer."""

import time

import pytest

from noise_catcher.storage import NoiseDB


@pytest.fixture
def db() -> NoiseDB:
    """Create an in-memory database for testing."""
    database = NoiseDB(":memory:")
    database.initialize()
    return database


class TestInitialization:
    """Database schema creation."""

    def test_creates_tables(self, db: NoiseDB) -> None:
        """Initialize creates the expected tables."""
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [r[0] for r in tables]
        assert "noise_samples" in table_names
        assert "noise_events" in table_names

    def test_is_idempotent(self, db: NoiseDB) -> None:
        """Calling initialize twice does not error."""
        db.initialize()  # should not raise

    def test_samples_table_schema(self, db: NoiseDB) -> None:
        """Samples table has correct columns."""
        info = db.conn.execute("PRAGMA table_info(noise_samples)").fetchall()
        cols = {r[1]: r[2] for r in info}
        assert "ts" in cols
        assert "leq_db" in cols
        assert "lpeak_db" in cols

    def test_wal_mode_enabled(self, db: NoiseDB) -> None:
        """WAL journal mode for file-based databases (not :memory:)."""
        if db.db_path == ":memory:":
            pytest.skip("WAL not applicable to in-memory databases")
        mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.upper() == "WAL"


class TestInsert:
    """Writing samples to the database."""

    def test_insert_single_sample(self, db: NoiseDB) -> None:
        """Insert one sample and verify it's stored."""
        ts = time.time()
        db.insert_sample(ts, 45.2, 62.1)
        row = db.conn.execute(
            "SELECT ts, leq_db, lpeak_db FROM noise_samples WHERE ts = ?", (ts,)
        ).fetchone()
        assert row is not None
        assert row[1] == pytest.approx(45.2)
        assert row[2] == pytest.approx(62.1)

    def test_insert_batch(self, db: NoiseDB) -> None:
        """Insert multiple samples at once."""
        samples = [
            (1000.0, 40.0, 55.0),
            (1001.0, 42.0, 58.0),
            (1002.0, 38.0, 50.0),
        ]
        db.insert_samples(samples)
        count = db.conn.execute("SELECT COUNT(*) FROM noise_samples").fetchone()[0]
        assert count == 3

    def test_replace_on_conflict(self, db: NoiseDB) -> None:
        """Inserting same timestamp twice updates the row (no duplicates)."""
        ts = time.time()
        db.insert_sample(ts, 40.0, 50.0)
        db.insert_sample(ts, 45.0, 55.0)  # same timestamp
        rows = db.conn.execute(
            "SELECT leq_db, lpeak_db FROM noise_samples WHERE ts = ?", (ts,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(45.0)  # updated value


class TestQuery:
    """Reading samples from the database."""

    def test_query_range_returns_correct_samples(self, db: NoiseDB) -> None:
        """Query by time range returns only samples within that window."""
        db.insert_samples(
            [
                (1000.0, 40.0, 50.0),
                (1001.0, 42.0, 52.0),
                (1002.0, 44.0, 54.0),
                (1003.0, 46.0, 56.0),
            ]
        )
        results = db.query_range(1000.5, 1002.5)
        assert len(results) == 2
        timestamps = [r[0] for r in results]
        assert 1001.0 in timestamps
        assert 1002.0 in timestamps

    def test_query_range_empty(self, db: NoiseDB) -> None:
        """Empty range returns no results."""
        results = db.query_range(0, 1)
        assert results == []

    def test_query_range_inclusive_bounds(self, db: NoiseDB) -> None:
        """Range query includes samples at the boundary."""
        db.insert_sample(1000.0, 40.0, 50.0)
        results = db.query_range(1000.0, 1000.0)
        assert len(results) == 1

    def test_get_latest_timestamp(self, db: NoiseDB) -> None:
        """Returns the most recent timestamp or None."""
        assert db.get_latest_timestamp() is None
        db.insert_sample(1000.0, 40.0, 50.0)
        db.insert_sample(2000.0, 42.0, 52.0)
        assert db.get_latest_timestamp() == pytest.approx(2000.0)

    def test_count_samples(self, db: NoiseDB) -> None:
        """Count returns total number of stored samples."""
        assert db.count_samples() == 0
        db.insert_samples([(i, 40.0, 50.0) for i in range(100)])
        assert db.count_samples() == 100
