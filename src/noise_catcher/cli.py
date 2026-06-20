"""CLI entry point for the Noise Catcher.

Usage:
    noise-catcher record --duration 60 [--db noise.db]
    noise-catcher graph [--db noise.db] [--date 2026-06-21] [--output graph.png]
    noise-catcher list-devices
"""

import sys
from datetime import date, datetime

import click

from noise_catcher import __version__
from noise_catcher.capture import AudioCapture
from noise_catcher.dsp import process_chunk
from noise_catcher.graph import render_daily_graph
from noise_catcher.storage import NoiseDB


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Noise Catcher — environmental noise monitoring and analysis."""
    pass


@main.command()
@click.option(
    "--duration",
    "-d",
    type=float,
    default=60.0,
    show_default=True,
    help="Recording duration in seconds.",
)
@click.option(
    "--db",
    "db_path",
    type=click.Path(),
    default="noise_catcher.db",
    show_default=True,
    help="SQLite database path.",
)
@click.option(
    "--device",
    type=str,
    default=None,
    help="Audio input device name or index (use list-devices to see options).",
)
@click.option(
    "--sample-rate",
    "-r",
    type=int,
    default=48000,
    show_default=True,
    help="Sample rate in Hz.",
)
@click.option(
    "--chunk-duration",
    type=float,
    default=1.0,
    show_default=True,
    help="Processing chunk duration in seconds.",
)
def record(
    duration: float,
    db_path: str,
    device: str | None,
    sample_rate: int,
    chunk_duration: float,
) -> None:
    """Record audio and store dB(A) levels in the database."""
    cap = AudioCapture(device=device, sample_rate=sample_rate)

    # List available devices if device lookup fails
    try:
        # Test device access
        cap.record_blocking(0.1)
    except Exception as e:
        click.echo(f"Error accessing audio device: {e}", err=True)
        click.echo("\nAvailable input devices:", err=True)
        for dev in cap.list_devices():
            click.echo(
                f"  [{dev['index']}] {dev['name']} "
                f"({dev['channels']} ch, {dev['default_samplerate']} Hz)",
                err=True,
            )
        sys.exit(1)

    db = NoiseDB(db_path)
    db.initialize()

    n_chunks = int(duration / chunk_duration)
    click.echo(
        f"Recording {duration}s at {sample_rate} Hz → {db_path} "
        f"({n_chunks} chunks of {chunk_duration}s)"
    )

    samples_buffer: list[tuple[float, float, float]] = []

    total_samples = 0

    try:
        import time as _time

        for i, chunk in enumerate(cap.record_stream(chunk_duration_s=chunk_duration)):
            leq = process_chunk(chunk, sample_rate)
            # Estimate peak: 6 dB above Leq is a typical conservative estimate
            # For real calibrated measurements, compute actual peak from samples
            lpeak = leq + 6.0
            ts = _time.time()

            samples_buffer.append((ts, leq, lpeak))

            # Batch insert every 10 chunks for performance
            if len(samples_buffer) >= 10:
                db.insert_samples(samples_buffer)
                total_samples += len(samples_buffer)
                samples_buffer.clear()

            click.echo(f"  [{ts:.1f}] Leq: {leq:.1f} dB(A)")

            if i + 1 >= n_chunks:
                break
    except KeyboardInterrupt:
        click.echo("\nRecording stopped by user.")
    finally:
        # Flush remaining samples
        if samples_buffer:
            db.insert_samples(samples_buffer)
            total_samples += len(samples_buffer)
        db.close()

    click.echo(f"Done. {total_samples} samples stored in {db_path}")


@main.command()
@click.option(
    "--db",
    "db_path",
    type=click.Path(exists=True),
    default="noise_catcher.db",
    show_default=True,
    help="SQLite database path.",
)
@click.option(
    "--date",
    "day_str",
    type=str,
    default=None,
    help="Date to graph in YYYY-MM-DD format (default: yesterday).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output PNG path (default: noise_<date>.png).",
)
@click.option(
    "--per-second/--per-minute",
    default=False,
    help="Plot per-second (detailed) or per-minute (aggregated).",
)
def graph(
    db_path: str,
    day_str: str | None,
    output: str | None,
    per_second: bool,
) -> None:
    """Render a daily noise graph from the database."""
    day: date | None = None
    if day_str:
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
        except ValueError:
            click.echo(f"Invalid date: '{day_str}'. Use YYYY-MM-DD format.", err=True)
            sys.exit(1)

    click.echo(f"Rendering graph for {day or 'yesterday'}...")
    result = render_daily_graph(
        db_path,
        day=day,
        output_path=output,
        per_minute=not per_second,
    )
    click.echo(f"Graph saved to: {result}")


@main.command()
def list_devices() -> None:
    """List available audio input devices."""
    cap = AudioCapture()
    devices = cap.list_devices()
    if not devices:
        click.echo("No input devices found.")
        return

    click.echo("Available audio input devices:")
    for dev in devices:
        click.echo(
            f"  [{dev['index']}] {dev['name']} "
            f"({dev['channels']} ch, {dev['default_samplerate']} Hz)"
        )
