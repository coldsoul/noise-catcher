"""Noise event detection — loud pass-by detection using dB thresholding.

Identifies contiguous periods where Leq exceeds a threshold,
filters out short events, and merges nearby events.
"""

from dataclasses import dataclass

from noise_catcher.storage import NoiseDB

# Default detection parameters
DEFAULT_THRESHOLD_DB = 55.0  # dB above which we consider "loud"
DEFAULT_MIN_DURATION_S = 3.0  # seconds sustained to count as event
DEFAULT_COOLDOWN_S = 10.0  # seconds between events to avoid fragmentation


@dataclass
class NoiseEvent:
    """A detected loud noise event."""

    start_ts: float
    end_ts: float
    max_db: float
    duration_s: float


def detect_events(
    samples: list[tuple[float, float, float]],
    threshold_db: float = DEFAULT_THRESHOLD_DB,
    min_duration_s: float = DEFAULT_MIN_DURATION_S,
    cooldown_s: float = DEFAULT_COOLDOWN_S,
) -> list[NoiseEvent]:
    """Detect loud noise events from a sorted list of samples.

    Args:
        samples: List of (timestamp, leq_db, lpeak_db) tuples, sorted by timestamp.
        threshold_db: dB threshold — samples at or above this are "loud".
        min_duration_s: Minimum duration in seconds for a valid event.
        cooldown_s: Events within this many seconds are merged.

    Returns:
        List of detected NoiseEvent objects.
    """
    if not samples:
        return []

    # Step 1: Find contiguous periods where leq_db >= threshold
    raw_periods: list[list[tuple[float, float, float]]] = []
    current_period: list[tuple[float, float, float]] = []

    for sample in samples:
        ts, leq_db, lpeak_db = sample
        if leq_db >= threshold_db:
            current_period.append(sample)
        else:
            if current_period:
                raw_periods.append(current_period)
                current_period = []

    if current_period:
        raw_periods.append(current_period)

    # Step 2: Filter out periods shorter than min_duration_s
    filtered_periods = []
    for period in raw_periods:
        duration = period[-1][0] - period[0][0]
        if duration >= min_duration_s:
            filtered_periods.append(period)

    # Step 3: Convert filtered periods to NoiseEvent objects
    events = []
    for period in filtered_periods:
        start_ts = period[0][0]
        end_ts = period[-1][0]
        max_db = max(s[1] for s in period)  # max leq in the period
        duration_s = end_ts - start_ts
        events.append(NoiseEvent(start_ts, end_ts, max_db, duration_s))

    # Step 4: Merge events that are within cooldown_s of each other
    if not events:
        return []

    merged: list[NoiseEvent] = [events[0]]
    for event in events[1:]:
        prev = merged[-1]
        gap = event.start_ts - prev.end_ts
        if gap <= cooldown_s:
            # Merge: extend end_ts, update max_db, recalculate duration
            new_end = max(prev.end_ts, event.end_ts)
            new_max = max(prev.max_db, event.max_db)
            new_duration = new_end - prev.start_ts
            merged[-1] = NoiseEvent(prev.start_ts, new_end, new_max, new_duration)
        else:
            merged.append(event)

    return merged


def store_events(db: NoiseDB, events: list[NoiseEvent]) -> int:
    """Insert detected events into the noise_events table.

    Args:
        db: An initialized NoiseDB instance.
        events: List of NoiseEvent objects to store.

    Returns:
        Number of events stored.
    """
    count = 0
    for event in events:
        db.insert_event(event.start_ts, event.end_ts, event.max_db, event.duration_s)
        count += 1
    return count
