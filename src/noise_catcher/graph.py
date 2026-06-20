"""Daily noise graph rendering using matplotlib.

Generates a PNG time-series graph with:
- Per-minute Leq line
- Night hours (22:00-06:00) highlighted
- WHO guideline reference line (55 dB)
- Peak markers
"""

from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from noise_catcher.storage import NoiseDB

# WHO night noise guideline (2009): 55 dB Lnight
WHO_NIGHT_GUIDELINE_DB = 55

# Night hours for highlighting
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 6


def _as_date(d: date | None) -> date:
    """Return date, defaulting to yesterday so we graph a complete day."""
    if d is None:
        return date.today() - timedelta(days=1)
    return d


def render_daily_graph(
    db_path: str,
    day: date | None = None,
    output_path: str | None = None,
    per_minute: bool = True,
) -> str:
    """Render a daily noise graph as a PNG.

    Args:
        db_path: Path to the SQLite database.
        day: Date to graph (defaults to yesterday).
        output_path: Output PNG path (defaults to 'noise_<date>.png').
        per_minute: If True, aggregate to 1-minute Leq; otherwise plot every second.

    Returns:
        Path to the generated PNG file.
    """
    target_date = _as_date(day)

    if output_path is None:
        output_path = f"noise_{target_date.isoformat()}.png"

    db = NoiseDB(db_path)
    db.initialize()

    # Query the full day's data
    start_ts = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0).timestamp()
    end_ts = start_ts + 86400  # 24 hours

    rows = db.query_range(start_ts, end_ts)
    db.close()

    # Prepare data
    if not rows:
        # Generate empty graph with "no data" message
        fig, ax = plt.subplots(figsize=(16, 6))
        ax.text(
            0.5,
            0.5,
            "No data for this day",
            ha="center",
            va="center",
            fontsize=18,
            color="gray",
            transform=ax.transAxes,
        )
        ax.set_title(f"Noise Levels — {target_date.isoformat()}")
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
        return output_path

    timestamps = [datetime.fromtimestamp(r[0]) for r in rows]
    leq_values = [r[1] for r in rows]

    # Aggregate to per-minute if requested
    if per_minute and len(timestamps) > 60:
        timestamps, leq_values = _aggregate_per_minute(timestamps, leq_values)

    # Create figure
    fig, ax = plt.subplots(figsize=(16, 6))

    # Highlight night hours
    _highlight_night_hours(ax, target_date)

    # Plot noise line
    ax.plot(timestamps, leq_values, linewidth=0.5, color="#1f77b4", label="Leq (dB(A))")

    # WHO guideline reference
    ax.axhline(
        y=WHO_NIGHT_GUIDELINE_DB,
        color="red",
        linestyle="--",
        linewidth=1,
        alpha=0.7,
        label=f"WHO night guideline ({WHO_NIGHT_GUIDELINE_DB} dB)",
    )

    # Format axes
    ax.set_xlabel("Time of day")
    ax.set_ylabel("Sound Level (dB(A))")
    ax.set_title(f"Noise Levels — {target_date.isoformat()}")
    ax.set_ylim(bottom=0, top=max(100, max(leq_values) + 10))
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)

    # Time axis formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax.set_xlim(
        datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0),
        datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59),
    )
    fig.autofmt_xdate()

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

    return output_path


def _aggregate_per_minute(
    timestamps: list[datetime], leq_values: list[float]
) -> tuple[list[datetime], list[float]]:
    """Aggregate per-second Leq values to per-minute averages (energy mean)."""
    import math

    if not timestamps:
        return [], []

    minute_bins: dict[datetime, list[float]] = {}
    for ts, leq in zip(timestamps, leq_values, strict=True):
        minute_key = ts.replace(second=0, microsecond=0)
        minute_bins.setdefault(minute_key, []).append(leq)

    result_ts: list[datetime] = []
    result_leq: list[float] = []

    for minute_key in sorted(minute_bins.keys()):
        leqs = minute_bins[minute_key]
        # Energy average: 10*log10(mean(10^(leq/10)))
        energy_sum = sum(10.0 ** (leq / 10.0) for leq in leqs)
        avg_leq = 10.0 * math.log10(energy_sum / len(leqs))
        result_ts.append(minute_key)
        result_leq.append(avg_leq)

    return result_ts, result_leq


def _highlight_night_hours(ax: plt.Axes, day: date) -> None:
    """Shade night hours (22:00-06:00) on the graph."""
    from datetime import datetime

    # Night portion at end of day: 22:00 - 23:59
    night_start_end = datetime(day.year, day.month, day.day, NIGHT_START_HOUR, 0, 0)
    night_end_day_end = datetime(day.year, day.month, day.day, 23, 59, 59)

    ax.axvspan(
        night_start_end,
        night_end_day_end,
        alpha=0.1,
        color="navy",
        label="Night (22:00-06:00)",
    )

    # Night portion at start of day: 00:00 - 06:00
    day_start = datetime(day.year, day.month, day.day, 0, 0, 0)
    night_end_start = datetime(day.year, day.month, day.day, NIGHT_END_HOUR, 0, 0)

    ax.axvspan(day_start, night_end_start, alpha=0.1, color="navy")
