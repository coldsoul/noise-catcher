"""Tests for the dashboard generator (archive page + summary graphs)."""

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
        # Sorted: [50, 60], n=2
        # L90 (10th percentile): (2-1)*0.1 = 0.1 → 50 + 0.1*10 = 51.0
        assert result["L90"] == pytest.approx(51.0, abs=0.5)
        # L50 (50th percentile): (2-1)*0.5 = 0.5 → 50 + 0.5*10 = 55.0
        assert result["L50"] == pytest.approx(55.0, abs=0.5)
        # L10 (90th percentile): (2-1)*0.9 = 0.9 → 50 + 0.9*10 = 59.0
        assert result["L10"] == pytest.approx(59.0, abs=0.5)
        # Leq: 10*log10(mean(10^5 + 10^6))
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
        # Sorted: [40, 50, 60], n=3
        # L90 (10th pctl): (3-1)*0.1 = 0.2 → 40 + 0.2*10 = 42.0
        assert result["L90"] == pytest.approx(42.0, abs=1.0)
        # L50 (50th pctl): (3-1)*0.5 = 1.0 → 50.0
        assert result["L50"] == pytest.approx(50.0, abs=1.0)
        # L10 (90th pctl): (3-1)*0.9 = 1.8 → 50 + 0.8*10 = 58.0
        assert result["L10"] == pytest.approx(58.0, abs=1.0)
        # Leq: energy avg of [40,50,60]
        energy = (10**4 + 10**5 + 10**6) / 3.0
        assert result["Leq"] == pytest.approx(10.0 * math.log10(energy), abs=1.0)


# ======================================================================
# DashboardGenerator — helpers
# ======================================================================


@pytest.fixture
def gh_pages_dir() -> str:
    """Create a temporary gh-pages checkout directory."""
    tmp = tempfile.mkdtemp(suffix="-gh-pages")
    graphs_dir = os.path.join(tmp, "graphs")
    os.makedirs(graphs_dir, exist_ok=True)
    return tmp


@pytest.fixture
def db_with_data() -> str:
    """Create a temporary database with a few days of synthetic data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_file:
        db_path = db_file.name

    db = NoiseDB(db_path)
    db.initialize()

    # Insert 3 days of data
    base_day = date(2026, 6, 19)
    for day_offset in range(3):
        day = base_day + timedelta(days=day_offset)
        start_ts = datetime(day.year, day.month, day.day, 0, 0, 0).timestamp()
        samples: list[tuple[float, float, float]] = []
        for second in range(86400):
            # Vary Leq: quiet night (30 dB), louder day (45-55 dB)
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
        """Graph files in directory are listed as thumbnails."""
        # Create fake graph PNGs
        graphs_dir = os.path.join(gh_pages_dir, "graphs")
        for day_str in ["2026-06-19", "2026-06-20", "2026-06-21"]:
            path = os.path.join(graphs_dir, f"noise_{day_str}.png")
            with open(path, "w") as f:
                f.write("FAKE_PNG")  # not a real PNG, just for listing

        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        result = gen.generate_archive_page()
        assert os.path.exists(result)
        with open(result, encoding="utf-8") as f:
            html = f.read()
        assert "2026-06-19" in html
        assert "2026-06-20" in html
        assert "2026-06-21" in html
        assert "graphs/noise_2026-06-19.png" in html
        assert "thumbnail-grid" in html

    def test_archive_page_has_navigation_links(
        self, gh_pages_dir: str,
    ) -> None:
        """Archive page includes links to index, weekly, and monthly."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        result = gen.generate_archive_page()
        with open(result, encoding="utf-8") as f:
            html = f.read()
        assert 'href="index.html"' in html
        assert 'href="weekly_summary.png"' in html
        assert 'href="monthly_summary.png"' in html


# ======================================================================
# Summary graph tests
# ======================================================================


class TestSummaryGraphs:
    """Tests for weekly and monthly summary PNG generation."""

    def _is_valid_png(self, path: str) -> bool:
        """Check if file exists, is non-empty, and has PNG header."""
        if not os.path.exists(path):
            return False
        size = os.path.getsize(path)
        if size < 100:  # PNGs are at least a few hundred bytes
            return False
        with open(path, "rb") as f:
            header = f.read(8)
        return header == b"\x89PNG\r\n\x1a\n"

    def test_weekly_summary_generates_png(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """Weekly summary creates a valid PNG."""
        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        end_date = date(2026, 6, 21)
        result = gen.generate_weekly_summary(end_date=end_date)
        assert result.endswith("weekly_summary.png")
        assert self._is_valid_png(result)

    def test_monthly_summary_generates_png(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """Monthly summary creates a valid PNG."""
        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        end_date = date(2026, 6, 21)
        result = gen.generate_monthly_summary(end_date=end_date)
        assert result.endswith("monthly_summary.png")
        assert self._is_valid_png(result)

    def test_weekly_summary_no_data(self, gh_pages_dir: str) -> None:
        """Weekly summary with empty DB still produces a PNG."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        result = gen.generate_weekly_summary(end_date=date(2026, 6, 21))
        assert self._is_valid_png(result)

    def test_monthly_summary_no_data(self, gh_pages_dir: str) -> None:
        """Monthly summary with empty DB still produces a PNG."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        result = gen.generate_monthly_summary(end_date=date(2026, 6, 21))
        assert self._is_valid_png(result)


# ======================================================================
# End-to-end
# ======================================================================


class TestDashboardGenerator:
    """Full dashboard generation end-to-end."""

    def test_generate_dashboard_runs_all(
        self, gh_pages_dir: str, db_with_data: str,
    ) -> None:
        """Calling generate_dashboard() produces all expected outputs."""
        # Create at least one graph to exercise the archive
        graphs_dir = os.path.join(gh_pages_dir, "graphs")
        path = os.path.join(graphs_dir, "noise_2026-06-21.png")
        with open(path, "w") as f:
            f.write("FAKE_PNG")

        gen = DashboardGenerator(db_with_data, gh_pages_dir)
        gen.generate_dashboard()

        # Check all outputs exist
        assert os.path.exists(os.path.join(gh_pages_dir, "archive.html"))
        assert os.path.exists(os.path.join(gh_pages_dir, "weekly_summary.png"))
        assert os.path.exists(os.path.join(gh_pages_dir, "monthly_summary.png"))

        # Verify HTML is not empty
        with open(os.path.join(gh_pages_dir, "archive.html"), encoding="utf-8") as f:
            html = f.read()
        assert len(html) > 500  # substantial HTML content
        assert "Noise Catcher" in html

    def test_generate_dashboard_empty_db(self, gh_pages_dir: str) -> None:
        """Dashboard generation with empty DB produces all files (no crash)."""
        gen = DashboardGenerator(":memory:", gh_pages_dir)
        gen.generate_dashboard()

        assert os.path.exists(os.path.join(gh_pages_dir, "archive.html"))
        assert os.path.exists(os.path.join(gh_pages_dir, "weekly_summary.png"))
        assert os.path.exists(os.path.join(gh_pages_dir, "monthly_summary.png"))
