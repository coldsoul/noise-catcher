#!/usr/bin/env python3
"""Generate synthetic noise data for testing the full Noise Catcher pipeline.

Creates a SQLite database with 30 days of realistic environmental noise data:
- Daytime (06:00-22:00): 35-60 dB(A) with traffic peaks
- Nighttime (22:00-06:00): 20-40 dB(A) with occasional loud vehicle pass-bys
- Weekend days: slightly quieter overall

Then runs the dashboard generator against both the DB and a fake gh-pages dir
to produce archive.html, summaries, all_time_trend.png, and daily graph PNGs.
"""

import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from noise_catcher.dashboard import DashboardGenerator
from noise_catcher.graph import render_daily_graph
from noise_catcher.storage import NoiseDB

SAMPLE_RATE = 48000
DAYS = 30
END_DATE = date.today()


def generate_realistic_leq(hour: int, minute: int, is_weekend: bool) -> float:
    """Return a realistic dB(A) value for a given time of day.

    Simulates:
    - Night quiet (22-06): 20-35 dB, occasional loud pass-by
    - Morning rush (07-09): 45-60 dB
    - Daytime (09-17): 35-55 dB
    - Evening rush (17-19): 45-60 dB
    - Late evening (19-22): 30-45 dB
    """
    base: float

    if 0 <= hour < 6:
        base = 25.0 + random.gauss(0, 3)
    elif 6 <= hour < 7:
        base = 30.0 + random.gauss(0, 4)
    elif 7 <= hour < 9:
        base = 48.0 + random.gauss(0, 5)
    elif 9 <= hour < 17:
        base = 40.0 + random.gauss(0, 5)
    elif 17 <= hour < 19:
        base = 47.0 + random.gauss(0, 5)
    elif 19 <= hour < 22:
        base = 35.0 + random.gauss(0, 4)
    else:  # 22-24
        base = 25.0 + random.gauss(0, 3)

    if is_weekend and 9 <= hour < 17:
        base -= 3.0  # quieter weekends

    # Occasional loud event (car, motorcycle)
    if random.random() < 0.02:
        base += random.uniform(15, 30)

    # Occasional very loud motorcycle at night
    if hour < 6 and random.random() < 0.005:
        base += random.uniform(30, 50)

    return max(5.0, base)


def populate_database(db_path: str, days: int = DAYS) -> int:
    """Fill the database with *days* of per-minute synthetic noise data.

    Returns total number of samples inserted.
    """
    db = NoiseDB(db_path)
    db.initialize()

    end = END_DATE
    start = end - timedelta(days=days - 1)

    total = 0
    buffer: list[tuple[float, float, float]] = []

    for day_offset in range(days):
        current_date = start + timedelta(days=day_offset)
        is_weekend = current_date.weekday() >= 5

        # Generate per-minute data for this day
        for hour in range(24):
            for minute in range(60):
                ts = datetime(
                    current_date.year, current_date.month, current_date.day,
                    hour, minute, 0,
                ).timestamp()

                leq = generate_realistic_leq(hour, minute, is_weekend)
                lpeak = leq + random.uniform(3, 12)

                buffer.append((ts, leq, lpeak))

                if len(buffer) >= 500:
                    db.insert_samples(buffer)
                    total += len(buffer)
                    buffer.clear()

        print(
            f"  {current_date.isoformat()} — "
            f"{'weekend' if is_weekend else 'weekday'}: {total} samples so far"
        )

    if buffer:
        db.insert_samples(buffer)
        total += len(buffer)

    db.close()
    print(f"\nTotal: {total} samples across {days} days")
    return total


def generate_daily_graphs(db_path: str, output_dir: str, days: int = DAYS) -> list[str]:
    """Render per-day PNG graphs for visual testing."""
    end = END_DATE
    start = end - timedelta(days=days - 1)
    graphs_dir = Path(output_dir)
    graphs_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for day_offset in range(days):
        current = start + timedelta(days=day_offset)
        output = str(graphs_dir / f"noise_{current.isoformat()}.png")
        render_daily_graph(db_path, day=current, output_path=output)
        paths.append(output)

    print(f"Generated {len(paths)} daily graph PNGs")
    return paths


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent

    # Use a temp DB for the test data
    db_path = str(project_root / "test_data.db")

    print(f"Generating {DAYS} days of synthetic noise data...")
    populate_database(db_path, DAYS)

    # Use a persistent output directory
    gh_pages = project_root / "test-site"
    (gh_pages / "graphs").mkdir(parents=True, exist_ok=True)
    (gh_pages / "summaries").mkdir(parents=True, exist_ok=True)

    print(f"\nRendering daily graphs → {gh_pages}/graphs/")
    generate_daily_graphs(db_path, str(gh_pages / "graphs"), DAYS)

    print(f"\nGenerating dashboard → {gh_pages}")
    dg = DashboardGenerator(db_path=db_path, gh_pages_dir=str(gh_pages))
    dg.generate_dashboard()

    print(f"\nTest site ready at: {gh_pages}")
    print(f"  Database:       {db_path}")
    print(f"  Archive:        {gh_pages}/archive.html")
    print(f"  All-time trend: {gh_pages}/all_time_trend.png")
    print(f"  Summaries:      {gh_pages}/summaries/")
    print(f"  Daily graphs:   {gh_pages}/graphs/")
    print(f"\nOpen in browser:  open {gh_pages}/archive.html")


if __name__ == "__main__":
    main()
