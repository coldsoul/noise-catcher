"""Tests for the dashboard generator (archive page + summary graphs + trend)."""

import math
import os
import tempfile
from datetime import date, datetime, timedelta

import pytest

from noise_catcher.dashboard import DashboardGenerator, compute_statistical_levels
from noise_catcher.storage import NoiseDB

# ======================================================================
# compute_statistical_levels
# ======================================================================


class TestComputeStatisticalLevels:
    """Unit tests for the L10/L50/L90/Leq computation."""

    def test_constant_values(self) -> None:
        """All identical values → every level equals that value."""
        vals = [55.0] * 100
        result = compute_statistical_levels(vals)
        assert result["L10"] == pytest.approx(55.0)
        assert result["L50"] == pytest.approx(55.0)
        assert result["L90"] == pytest.approx(55.0)
        assert result["Leq"] == pytest.approx(55.0)

    def test_known_values(self) -> None:
        """Two distinct values produce predictable percentiles."""
        vals = [50.0, 60.0]
        result = compute_statistical_levels(vals)
        assert result["L90"] == pytest.approx(51.0, abs=0.5)
        assert result["L50"] == pytest.approx(55.0, abs=0.5)
        assert result["L10"] == pytest.approx(59.0, abs=0.5)
        energy_mean = (10**5 + 10**6) / 2.0
        expected_leq = 10.0 * math.log10(energy_mean)
        assert result["Leq"] == pytest.approx(expected_leq, abs=0.5)

    def test_empty_input(self) -> None:
        """Empty input returns all zeros."""
        result = compute_statistical_levels([])
        assert result == {"L10": 0.0, "L50": 0.0, "L90": 0.0, "Leq": 0.0}

    def test_single_value(self) -> None:
        """Single value → all levels equal that value."""
        result = compute_statistical_levels([42.5])
        assert result["L10"] == pytest.approx(42.5)
        assert result["L50"] == pytest.approx(42.5)
        assert result["L90"] == pytest.approx(42.5)
        assert result["Leq"] == pytest.approx(42.5)

    def test_three_values_symmetric(self) -> None:
        """Three symmetric values around 50."""
        vals = [40.0, 50.0, 60.0]
        result = compute_statistical_levels(vals)
        assert result["L90"] == pytest.approx(42.0, abs=1.0)
        assert result["L50"] == pytest.approx(50.0, abs=1.0)
        assert result["L10"] == pytest.approx(58.0, abs=1.0)
        energy = (10**4 + 10**5 + 10**6) / 3.0
        assert result["Leq"] == pytest.approx(10.0 * math.log10(energy), abs=1.0)


# ======================================================================
# DashboardGenerator — helpers
# ======================================================================


@pytest.fixture
def gh_pages_dir() -> str:
    """Create a temporary gh-pages checkout directory."""
    tmp = tempfile.mkdtemp(suffix="-gh-pages")
    os.makedirs(os.path.join(tmp, "graphs"), exist_ok=True)
    return tmp


@pytest.fixture
def db_with_data() -> str:
    """Create a temporary database with a few days of synthetic data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_file:
        db_path = db_file.name

    db = NoiseDB(db_path)
    db.initialize()

    base_day = date(2026, 6, 19)
    for day_offset in range(5):  # 5 days for rolling avg tests
        day = base_day + timedelta(days=day_offset)
        start_ts = datetime(day.year, day.month, day.day, 0, 0, 0).timestamp()
        samples: list[tuple[float, float, float]] = []
        for second in range(86400):
            hour = second // 3600
            leq = (
                30.0 + (second % 60) * 0.1
                if hour >= 22 or hour < 6
                else 45.0 + (second % 300) * 0.05
            )
            samples.append((start_ts + second, leq, leq + 6.0))
        db.insert_samples(samples)

    db.close()
    return db_path


@pytest.fixture
def db_large() -> str:
    """Create a temp database with 35 days of data (enough for rolling avg)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_file:
        db_path = db_file.name

    db = NoiseDB(db_path)
    db.initialize()

    base_day = date(2026, 5, 20)
    for day_offset in range(35):
        day = base_day + timedelta(days=day_offset)
        start_ts = datetime(day.year, day.month, day.day, 0, 0, 0).timestamp()
        samples: list[tuple[float, float, float]] = []
        for second in range(86400):
            leq = 40.0 + (second % 3600) * 0.005
            samples.append((start_ts + second, leq, leq + 6.0))
        db.insert_samples(samples)

    db.close()
    return db_path


# ======================================================================
# PNG validation helper
# ======================================================================


def _is_valid_png(path: str) -> bool:
    """Check if file exists, is non-empty, and has PNG header."""
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) < 100:
        return False
    with open(path, "rb") as f:
        return f.read(8) == b"\x89PNG\r\n\x1a\n"


# ======================================================================
# Archive page tests
# ======================================================================


class TestArchivePage:
    """Tests for archive.html generation."""

    def test_archive_page_empty_directory(self, gh_pages_dir: str) -> None:
        """Empty graphs directory produces archive with 'no graphs' message."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        result = gen.generate_archive_page()
        assert os.path.exists(result)
        with open(result, encoding="utf-8") as f:
            html = f.read()
        assert "No graphs available yet" in html
        assert "graphs/</a>" not in html  # no thumbnail links

    def test_archive_page_lists_available_graphs(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """Graph files in directory are listed with month grouping."""
        graphs_dir = os.path.join(gh_pages_dir, "graphs")
        # Create graphs across two months
        for day_str in ["2026-05-31", "2026-06-01", "2026-06-02"]:
            path = os.path.join(graphs_dir, f"noise_{day_str}.png")
            with open(path, "w") as f:
                f.write("FAKE_PNG")

        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        result = gen.generate_archive_page()
        assert os.path.exists(result)
        with open(result, encoding="utf-8") as f:
            html = f.read()

        # Should have month grouping headers
        assert 'id="month-2026-06"' in html
        assert 'id="month-2026-05"' in html
        assert "2026 June" in html
        assert "2026 May" in html
        # Should have day counts
        assert "June (2 days)" in html or "June (2 day" in html
        assert "May (1 day)" in html or "May (1 day)" in html

        # Should list all graphs
        assert "graphs/noise_2026-06-01.png" in html
        assert "graphs/noise_2026-06-02.png" in html
        assert "graphs/noise_2026-05-31.png" in html

    def test_archive_page_has_navigation_links(
        self, gh_pages_dir: str,
    ) -> None:
        """Archive page includes links to index, summaries, and trend."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        result = gen.generate_archive_page()
        with open(result, encoding="utf-8") as f:
            html = f.read()
        assert 'href="index.html"' in html
        assert "All-Time Trend" in html
        assert 'href="all_time_trend.png"' in html


# ======================================================================
# Summary graph tests
# ======================================================================


class TestSummaryGraphs:
    """Tests for weekly and monthly summary PNG generation."""

    def test_weekly_summary_generates_png(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """Weekly summary creates a valid dated PNG in summaries/."""
        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        end_date = date(2026, 6, 21)
        result = gen.generate_weekly_summary(end_date=end_date)
        assert "summaries" in result
        assert result.endswith("weekly_2026-06-21.png")
        assert _is_valid_png(result)

    def test_monthly_summary_generates_png(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """Monthly summary creates a valid dated PNG in summaries/."""
        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        end_date = date(2026, 6, 21)
        result = gen.generate_monthly_summary(end_date=end_date)
        assert "summaries" in result
        assert result.endswith("monthly_2026-06.png")
        assert _is_valid_png(result)

    def test_weekly_summary_no_data(self, gh_pages_dir: str) -> None:
        """Weekly summary with empty DB still produces a PNG."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        result = gen.generate_weekly_summary(end_date=date(2026, 6, 21))
        assert _is_valid_png(result)

    def test_monthly_summary_no_data(self, gh_pages_dir: str) -> None:
        """Monthly summary with empty DB still produces a PNG."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        result = gen.generate_monthly_summary(end_date=date(2026, 6, 21))
        assert _is_valid_png(result)

    def test_summaries_not_overwritten(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """Running weekly summary twice with same end date produces
        the same filename (no timestamp or random suffix)."""
        gen = DashboardGenerator(db_with_data, gh_pages_dir)

        r1 = gen.generate_weekly_summary(end_date=date(2026, 6, 21))
        r2 = gen.generate_weekly_summary(end_date=date(2026, 6, 21))
        assert r1 == r2
        assert os.path.exists(r1)

        r3 = gen.generate_monthly_summary(end_date=date(2026, 6, 21))
        r4 = gen.generate_monthly_summary(end_date=date(2026, 6, 21))
        assert r3 == r4
        assert os.path.exists(r3)


# ======================================================================
# All-time trend graph
# ======================================================================


class TestAllTimeTrend:
    """Tests for the all-time trend graph."""

    def test_all_time_trend_generates_png(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """All-time trend with data produces a valid PNG."""
        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        result = gen.generate_all_time_trend()
        assert result.endswith("all_time_trend.png")
        assert _is_valid_png(result)

    def test_all_time_trend_empty_db(self, gh_pages_dir: str) -> None:
        """All-time trend with empty DB produces valid placeholder PNG."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        result = gen.generate_all_time_trend()
        assert _is_valid_png(result)

    def test_all_time_trend_large_dataset(
        self, gh_pages_dir: str, db_large: str,
    ) -> None:
        """All-time trend with 35+ days includes a rolling average line."""
        gen = DashboardGenerator(db_large, gh_pages_dir)
        result = gen.generate_all_time_trend()
        assert _is_valid_png(result)
        # 35 days of data should produce a non-trivial image
        assert os.path.getsize(result) > 2000


# ======================================================================
# End-to-end
# ======================================================================


class TestDashboardGenerator:
    """Full dashboard generation end-to-end."""

    def test_generate_dashboard_runs_all(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """Calling generate_dashboard() produces all expected outputs."""
        graphs_dir = os.path.join(gh_pages_dir, "graphs")
        path = os.path.join(graphs_dir, "noise_2026-06-21.png")
        with open(path, "w") as f:
            f.write("FAKE_PNG")

        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        outputs = gen.generate_dashboard()

        # Should return paths to all outputs
        assert len(outputs) == 4

        # Check all outputs exist
        assert os.path.exists(os.path.join(gh_pages_dir, "archive.html"))
        assert os.path.exists(os.path.join(gh_pages_dir, "all_time_trend.png"))

        # Summaries in summaries/
        summaries_dir = os.path.join(gh_pages_dir, "summaries")
        assert os.path.isdir(summaries_dir)

        # At least one weekly and one monthly file should exist
        weekly_files = [f for f in os.listdir(summaries_dir) if f.startswith("weekly_")]
        monthly_files = [f for f in os.listdir(summaries_dir) if f.startswith("monthly_")]
        assert len(weekly_files) >= 1
        assert len(monthly_files) >= 1

        # Verify HTML is not empty
        with open(os.path.join(gh_pages_dir, "archive.html"), encoding="utf-8") as f:
            html = f.read()
        assert len(html) > 500
        assert "Noise Catcher" in html

    def test_generate_dashboard_empty_db(
        self, gh_pages_dir: str,
    ) -> None:
        """Dashboard generation with empty DB produces all files (no crash)."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        outputs = gen.generate_dashboard()
        assert len(outputs) == 4
        assert os.path.exists(os.path.join(gh_pages_dir, "archive.html"))
        assert os.path.exists(os.path.join(gh_pages_dir, "all_time_trend.png"))

    def test_generate_dashboard_returns_paths(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """generate_dashboard() returns paths to all generated files."""
        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        outputs = gen.generate_dashboard()
        assert isinstance(outputs, list)
        assert len(outputs) == 4
        for path in outputs:
            assert os.path.exists(path), f"Output missing: {path}"
