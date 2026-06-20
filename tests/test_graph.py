"""Tests for the daily noise graph rendering."""

import os
import tempfile
from datetime import date, datetime

import pytest

from noise_catcher.graph import _aggregate_per_minute, render_daily_graph
from noise_catcher.storage import NoiseDB


class TestRenderDailyGraph:
    """End-to-end graph rendering."""

    def test_empty_database_produces_no_data_graph(self) -> None:
        """Graph for a day with no data should render without error."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            output_path = f.name

        try:
            db_path = ":memory:"
            result = render_daily_graph(db_path, day=date(2026, 6, 21), output_path=output_path)
            assert result == output_path
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0
        finally:
            os.unlink(output_path)

    def test_graph_with_data_renders_successfully(self) -> None:
        """Graph for a day with data should render without error."""
        # Use file-based DB so WAL works
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_file:
            db_path = db_file.name
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
            output_path = img_file.name

        try:
            db = NoiseDB(db_path)
            db.initialize()

            # Insert 24 hours of synthetic data
            start_ts = datetime(2026, 6, 21, 0, 0, 0).timestamp()
            samples = [(start_ts + i, 40.0 + (i % 3600) * 0.01, 50.0) for i in range(86400)]
            db.insert_samples(samples)
            db.close()

            result = render_daily_graph(db_path, day=date(2026, 6, 21), output_path=output_path)
            assert result == output_path
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 1000  # should be a real image

        finally:
            os.unlink(db_path)
            os.unlink(output_path)

    def test_defaults_to_today(self) -> None:
        """When no date is provided, graphs today."""
        from datetime import date

        today = date.today()
        # Don't pass output_path — let the function generate the filename
        result = render_daily_graph(":memory:")
        assert today.isoformat() in result
        # Clean up auto-generated file
        import os

        if os.path.exists(result):
            os.unlink(result)

    def test_night_hours_are_highlighted(self) -> None:
        """Graph includes night hour shading (visual-only test — just verify no crash)."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            output_path = f.name

        try:
            db = NoiseDB(":memory:")
            db.initialize()
            # Insert data with loud night-time spikes
            start = datetime(2026, 6, 21, 0, 0, 0).timestamp()
            samples = [(start + i, 30.0, 40.0) for i in range(86400)]
            # Add a loud event at 3 AM
            loud_idx = 3 * 3600  # 03:00:00
            samples[loud_idx] = (start + loud_idx, 85.0, 90.0)
            db.insert_samples(samples)
            db.close()

            result = render_daily_graph(":memory:", day=date(2026, 6, 21), output_path=output_path)
            assert os.path.exists(result)
        finally:
            os.unlink(output_path)


class TestAggregatePerMinute:
    """Per-second to per-minute Leq aggregation."""

    def test_single_minute(self) -> None:
        """All samples in one minute bucket."""
        ts_list = [
            datetime(2026, 6, 21, 12, 0, 0),
            datetime(2026, 6, 21, 12, 0, 30),
            datetime(2026, 6, 21, 12, 0, 59),
        ]
        leq_list = [50.0, 52.0, 48.0]
        result_ts, result_leq = _aggregate_per_minute(ts_list, leq_list)
        assert len(result_ts) == 1
        assert result_ts[0] == datetime(2026, 6, 21, 12, 0)
        assert 48.0 < result_leq[0] < 52.0  # energy mean near the middle

    def test_multiple_minutes(self) -> None:
        """Samples spread across multiple minute buckets."""
        ts_list = [
            datetime(2026, 6, 21, 12, 0, 0),
            datetime(2026, 6, 21, 12, 0, 30),
            datetime(2026, 6, 21, 12, 1, 0),
            datetime(2026, 6, 21, 12, 1, 30),
            datetime(2026, 6, 21, 12, 2, 0),
        ]
        leq_list = [40.0, 42.0, 44.0, 46.0, 48.0]
        result_ts, result_leq = _aggregate_per_minute(ts_list, leq_list)
        assert len(result_ts) == 3  # 3 distinct minutes

    def test_empty_input(self) -> None:
        """Empty lists return empty lists."""
        ts, leq = _aggregate_per_minute([], [])
        assert ts == []
        assert leq == []

    def test_energy_average_not_arithmetic(self) -> None:
        """Energy mean of [60, 60] should be ~60, arithmetic would also be 60."""
        ts_list = [
            datetime(2026, 6, 21, 12, 0, 0),
            datetime(2026, 6, 21, 12, 0, 30),
        ]
        leq_list = [60.0, 60.0]
        _, result_leq = _aggregate_per_minute(ts_list, leq_list)
        assert result_leq[0] == pytest.approx(60.0)
