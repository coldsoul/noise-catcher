"""Signal-handling wrapper for continuous 24/7 capture daemon.

Provides ``run_forever()`` which loops over 24-hour recording chunks,
rotates the database file daily, and handles SIGTERM/SIGINT for
graceful shutdown.
"""

import os
import signal
import sys
import time
from datetime import date, datetime
from pathlib import Path

from noise_catcher.capture import AudioCapture
from noise_catcher.dsp import process_chunk
from noise_catcher.storage import NoiseDB

# Module-level flag set by signal handlers
_shutdown_requested: bool = False


def _handle_signal(signum: int, frame) -> None:
    """Set shutdown flag on SIGTERM/SIGINT for graceful shutdown."""
    global _shutdown_requested
    _shutdown_requested = True
    signal_name = signal.Signals(signum).name
    print(f"Received {signal_name}, shutting down gracefully...", file=sys.stderr)


def _rotate_db(db_path: Path) -> str:
    """Rename an existing DB file to ``noise_catcher.YYYY-MM-DD.db``.

    If the target name already exists (e.g. multiple rotations on the same
    calendar day), a numeric suffix is appended.

    Args:
        db_path: Path to the current database file.

    Returns:
        The path of the rotated file.
    """
    today = date.today()
    rotated_name = f"noise_catcher.{today.isoformat()}.db"
    rotated_path = db_path.with_name(rotated_name)

    # Avoid overwriting existing rotated files (multiple rotations same day)
    counter = 1
    while rotated_path.exists():
        rotated_path = db_path.with_name(f"noise_catcher.{today.isoformat()}.{counter}.db")
        counter += 1

    os.rename(str(db_path), str(rotated_path))
    return str(rotated_path)


def is_shutdown_requested() -> bool:
    """Return whether a shutdown signal has been received."""
    return _shutdown_requested


def run_forever(
    db_path: str = "noise_catcher.db",
    chunk_duration: float = 1.0,
    sample_rate: int = 48000,
    device: str | None = None,
    duration: float = 86400.0,
) -> None:
    """Run continuous capture with daily DB rotation.

    Records audio in streaming fashion (avoiding large memory buffers),
    rotates the database file once per iteration, and handles
    SIGTERM/SIGINT for graceful shutdown.

    The outer loop runs until a shutdown signal is received:
        1. Rotate previous iteration's DB → ``noise_catcher.YYYY-MM-DD.db``
        2. Create a fresh database
        3. Record audio for *duration* seconds (streaming, chunk by chunk)
        4. Insert dB(A) measurements into the DB
        5. Repeat from step 1

    Args:
        db_path: Path to the SQLite database file.
        chunk_duration: Processing chunk duration in seconds (default 1s).
        sample_rate: Audio sample rate in Hz (default 48000).
        device: Audio input device name or index (default None = system default).
        duration: Recording duration per iteration in seconds (default 86400 = 24h).
    """
    # Register signal handlers
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    db_path_obj = Path(db_path)

    while not _shutdown_requested:
        # Rotate previous iteration's database if it exists
        if db_path_obj.exists():
            rotated = _rotate_db(db_path_obj)
            print(f"Rotated database to {rotated}", file=sys.stderr)

        # Create fresh database
        db = NoiseDB(str(db_path_obj))
        db.initialize()

        capture = AudioCapture(
            device=device,
            sample_rate=sample_rate,
            channels=1,
        )

        n_chunks = int(duration / chunk_duration)
        rec_start = time.time()
        samples_buffer: list[tuple[float, float, float]] = []

        print(
            f"Starting {duration}s recording chunk \u2192 {db_path} "
            f"({n_chunks} chunks of {chunk_duration}s)",
            file=sys.stderr,
        )

        try:
            stream = capture.record_stream(chunk_duration_s=chunk_duration)

            try:
                for i in range(n_chunks):
                    if _shutdown_requested:
                        break

                    try:
                        chunk = next(stream)
                    except StopIteration:
                        break

                    leq = process_chunk(chunk, sample_rate)
                    lpeak = leq + 6.0
                    ts = rec_start + i * chunk_duration

                    samples_buffer.append((ts, leq, lpeak))

                    if len(samples_buffer) >= 10:
                        db.insert_samples(samples_buffer)
                        samples_buffer.clear()

                    # Log progress every hour
                    if i > 0 and i % 3600 == 0:
                        elapsed_h = i // 3600
                        total_h = n_chunks // 3600
                        ts_str = datetime.fromtimestamp(ts).isoformat()
                        print(
                            f"  [{ts_str}] Hour {elapsed_h}/{total_h}, Leq: {leq:.1f} dB(A)",
                            file=sys.stderr,
                        )
            finally:
                stream.close()
        finally:
            # Flush remaining samples
            if samples_buffer:
                db.insert_samples(samples_buffer)
            db.close()

        if _shutdown_requested:
            print("Daemon shutdown complete.", file=sys.stderr)
            break

        print(
            "24-hour chunk complete. Rotating database and starting next chunk...",
            file=sys.stderr,
        )
