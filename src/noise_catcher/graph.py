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
    """Return date, defaulting to today for interactive use."""
    if d is None:
        return date.today()
    return d


def render_daily_graph(
    db_path: str,
    day: date | None = None,
    output_path: str | None = None,
    per_minute: bool = True,
    show_events: bool = True,
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
    events = db.query_events(start_ts, end_ts) if show_events else []
    db.close()

    # Prepare data
    if not rows:
        # Generate empty graph with helpful message
        fig, ax = plt.subplots(figsize=(16, 6))
        ax.text(
            0.5,
            0.6,
            f"No data for {target_date.isoformat()}",
            ha="center",
            va="center",
            fontsize=18,
            color="#666666",
            transform=ax.transAxes,
        )
        ax.text(
            0.5,
            0.4,
            "Record audio first: noise-catcher record --duration 60",
            ha="center",
            va="center",
            fontsize=12,
            color="#999999",
            transform=ax.transAxes,
        )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
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

    # Plot noise line
    ax.plot(timestamps, leq_values, linewidth=0.5, color="#1f77b4", label="Leq (dB(A))")

    # Annotate detected events
    if show_events:
        _render_events(ax, events, timestamps)

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
    ax.set_ylim(
        bottom=min(0, min(leq_values) - 10),
        top=max(100, max(leq_values) + 10),
    )
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color="black", linewidth=0.5, alpha=0.5)  # 0 dB reference

    # Time axis — auto-zoom for short recordings, full day for 24h data
    data_span = (timestamps[-1] - timestamps[0]).total_seconds()
    title = f"Noise Levels — {target_date.isoformat()}"

    if data_span < 3600:  # < 1 hour of data → zoom in
        padding = max(60, data_span * 0.1)  # at least 1 min padding
        ax.set_xlim(
            timestamps[0] - timedelta(seconds=padding),
            timestamps[-1] + timedelta(seconds=padding),
        )
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=max(1, int(data_span / 300))))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        title += f" (recording: {data_span:.0f}s)"
    else:
        # Full day view with night hour highlighting
        _highlight_night_hours(ax, target_date)
        ax.set_xlim(
            datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0),
            datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59),
        )
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    ax.set_title(title)
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


def _render_events(
    ax: plt.Axes,
    events: list[tuple[float, float, float, float, float]],
    timestamps: list[datetime],
) -> None:
    """Overlay detected noise events on the graph as red vertical spans.

    Each event from query_events is (id, start_ts, end_ts, max_db, duration_s).
    """
    if not events:
        return

    from datetime import datetime as dt

    for event in events:
        _id, start_ts, end_ts, max_db, duration_s = event
        start_dt = dt.fromtimestamp(start_ts)
        end_dt = dt.fromtimestamp(end_ts)

        # Red vertical span for the event duration
        ax.axvspan(
            start_dt,
            end_dt,
            alpha=0.15,
            color="red",
            label="Noise event" if event is events[0] else "",
        )

        # Red dot at the max_db level, centered in the event time window
        mid_dt = dt.fromtimestamp((start_ts + end_ts) / 2.0)
        ax.plot(mid_dt, max_db, marker="o", color="red", markersize=5, linestyle="None")
