"""Tests for noise event detection and storage."""


import pytest

from noise_catcher.events import (
    NoiseEvent,
    detect_events,
    store_events,
)
from noise_catcher.storage import NoiseDB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _samples_from_constant(
    leq_db: float, count: int, start_ts: float = 1000.0, step: float = 1.0
) -> list[tuple[float, float, float]]:
    """Generate a series of identical samples for testing."""
    return [(start_ts + i * step, leq_db, leq_db + 10.0) for i in range(count)]


def _seconds(count: int) -> list[tuple[float, float, float]]:
    """Generate consecutive 1-second samples at 60 dB (above threshold)."""
    return _samples_from_constant(60.0, count)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db() -> NoiseDB:
    """In-memory database for storage tests."""
    database = NoiseDB(":memory:")
    database.initialize()
    return database


# ---------------------------------------------------------------------------
# Test: detect_events
# ---------------------------------------------------------------------------

class TestDetectEvents:
    """Core event detection logic."""

    def test_no_events_below_threshold(self) -> None:
        """All samples below threshold → empty list."""
        samples = _samples_from_constant(40.0, 100)
        events = detect_events(samples)
        assert events == []

    def test_single_event_above_threshold(self) -> None:
        """Contiguous loud samples → one event."""
        samples = _seconds(10)  # 10 seconds at 60 dB
        events = detect_events(samples)
        assert len(events) == 1
        assert events[0].start_ts == pytest.approx(1000.0)
        assert events[0].end_ts == pytest.approx(1009.0)
        assert events[0].max_db == pytest.approx(60.0)
        assert events[0].duration_s == pytest.approx(9.0)

    def test_min_duration_filter(self) -> None:
        """Loud period shorter than min_duration → filtered out."""
        samples = _seconds(2)  # 2 seconds, below 3s min
        events = detect_events(samples, min_duration_s=3.0)
        assert events == []

    def test_min_duration_boundary(self) -> None:
        """Loud period exactly at min_duration → kept."""
        samples = _seconds(4)  # 4 samples → span of 3.0s → equal to min
        events = detect_events(samples, min_duration_s=3.0)
        assert len(events) == 1

    def test_multiple_separate_events(self) -> None:
        """Two loud periods separated by quiet → two events."""
        samples: list[tuple[float, float, float]] = []
        # Event 1: 5 loud seconds
        samples.extend(_samples_from_constant(60.0, 5, start_ts=1000.0))
        # Quiet gap: 15 seconds (exceeds default cooldown of 10s)
        samples.extend(_samples_from_constant(40.0, 15, start_ts=1005.0))
        # Event 2: 5 loud seconds
        samples.extend(_samples_from_constant(60.0, 5, start_ts=1020.0))

        events = detect_events(samples)
        assert len(events) == 2
        assert events[0].start_ts == pytest.approx(1000.0)
        assert events[1].start_ts == pytest.approx(1020.0)

    def test_cooldown_merges_nearby_events(self) -> None:
        """Two events within cooldown → merged into one."""
        samples: list[tuple[float, float, float]] = []
        # Event 1: 4 loud seconds (3s span, meets min_duration)
        samples.extend(_samples_from_constant(60.0, 4, start_ts=1000.0))
        # Short quiet gap: 2 seconds (within cooldown)
        samples.extend(_samples_from_constant(40.0, 2, start_ts=1004.0))
        # Event 2: 4 loud seconds
        samples.extend(_samples_from_constant(70.0, 4, start_ts=1006.0))

        events = detect_events(samples, min_duration_s=3.0, cooldown_s=5.0)
        assert len(events) == 1
        # Merged event spans from first loud start to last loud end
        assert events[0].start_ts == pytest.approx(1000.0)
        assert events[0].end_ts == pytest.approx(1009.0)
        assert events[0].max_db == pytest.approx(70.0)

    def test_cooldown_does_not_merge_distant_events(self) -> None:
        """Events separated by more than cooldown → remain separate."""
        samples: list[tuple[float, float, float]] = []
        samples.extend(_samples_from_constant(60.0, 4, start_ts=1000.0))
        # Long quiet gap: 15 seconds (exceeds cooldown)
        samples.extend(_samples_from_constant(40.0, 15, start_ts=1004.0))
        samples.extend(_samples_from_constant(60.0, 4, start_ts=1019.0))

        events = detect_events(samples, min_duration_s=3.0, cooldown_s=5.0)
        assert len(events) == 2

    def test_event_captures_peak(self) -> None:
        """Event.max_db equals max Leq in the period."""
        samples = [
            (1000.0, 55.0, 65.0),
            (1001.0, 62.0, 72.0),
            (1002.0, 58.0, 68.0),
            (1003.0, 70.0, 80.0),  # peak
            (1004.0, 60.0, 70.0),
        ]
        events = detect_events(samples, min_duration_s=3.0)
        assert len(events) == 1
        assert events[0].max_db == pytest.approx(70.0)

    def test_empty_input(self) -> None:
        """Empty sample list → empty events."""
        assert detect_events([]) == []

    def test_threshold_at_edge(self) -> None:
        """Samples exactly at threshold are included."""
        samples = _samples_from_constant(55.0, 5)  # exactly threshold
        events = detect_events(samples, threshold_db=55.0, min_duration_s=3.0)
        assert len(events) == 1

    def test_just_below_threshold(self) -> None:
        """Samples just below threshold are excluded."""
        samples = _samples_from_constant(54.999, 5)
        events = detect_events(samples, threshold_db=55.0, min_duration_s=3.0)
        assert events == []


# ---------------------------------------------------------------------------
# Test: store_events
# ---------------------------------------------------------------------------

class TestStoreEvents:
    """Persisting events to the database."""

    def test_store_single_event(self, db: NoiseDB) -> None:
        """A single event can be stored and retrieved."""
        event = NoiseEvent(start_ts=1000.0, end_ts=1010.0, max_db=65.0, duration_s=10.0)
        count = store_events(db, [event])
        assert count == 1

    def test_store_and_query_events(self, db: NoiseDB) -> None:
        """Stores events, queries them back with correct values."""
        events = [
            NoiseEvent(start_ts=1000.0, end_ts=1010.0, max_db=65.0, duration_s=10.0),
            NoiseEvent(start_ts=2000.0, end_ts=2010.0, max_db=70.0, duration_s=10.0),
        ]
        store_events(db, events)

        # Query all events
        rows = db.query_events(0, 99999)
        assert len(rows) == 2
        # Each row: (id, start_ts, end_ts, max_db, duration_s)
        assert rows[0][1] == pytest.approx(1000.0)
        assert rows[0][2] == pytest.approx(1010.0)
        assert rows[0][3] == pytest.approx(65.0)
        assert rows[0][4] == pytest.approx(10.0)
        assert rows[1][1] == pytest.approx(2000.0)

    def test_store_empty_list(self, db: NoiseDB) -> None:
        """Empty event list → count 0, no rows inserted."""
        count = store_events(db, [])
        assert count == 0
        rows = db.conn.execute("SELECT COUNT(*) FROM noise_events").fetchone()
        assert rows[0] == 0


# ---------------------------------------------------------------------------
# Test: detect → store pipeline
# ---------------------------------------------------------------------------

class TestPipeline:
    """End-to-end detection and storage pipeline."""

    def test_detect_then_store(self, db: NoiseDB) -> None:
        """Detect events from samples, store them, query back."""
        samples = _seconds(60)  # 60 seconds of continuous 60 dB
        events = detect_events(samples, min_duration_s=3.0)
        assert len(events) == 1

        count = store_events(db, events)
        assert count == 1

        rows = db.query_events(0, 99999)
        assert len(rows) == 1
        assert rows[0][1] == pytest.approx(1000.0)
        assert rows[0][3] == pytest.approx(60.0)
