"""CLI entry point for the Noise Catcher.

Usage:
    noise-catcher record --duration 60 [--db noise.db]
    noise-catcher graph [--db noise.db] [--date 2026-06-21] [--output graph.png]
    noise-catcher list-devices
"""

import sys
from datetime import date, datetime

import click
import numpy as np
import sounddevice as sd

from noise_catcher import __version__
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
    db = NoiseDB(db_path)
    db.initialize()

    n_chunks = int(duration / chunk_duration)
    click.echo(
        f"Recording {duration}s at {sample_rate} Hz → {db_path} "
        f"({n_chunks} chunks of {chunk_duration}s)"
    )

    # Use blocking sd.rec() — simpler and more reliable than callback streaming
    total_frames = int(sample_rate * duration)
    try:
        recording = sd.rec(
            total_frames,
            samplerate=sample_rate,
            channels=1,
            device=device,
            dtype="float32",
        )
        sd.wait()
    except Exception as e:
        click.echo(f"Error recording audio: {e}", err=True)
        try:
            devs = sd.query_devices()
            input_devs = [(i, d) for i, d in enumerate(devs) if d["max_input_channels"] > 0]
            if input_devs:
                click.echo("\nAvailable input devices:", err=True)
                for idx, dev in input_devs:
                    click.echo(
                        f"  [{idx}] {dev['name']} "
                        f"({dev['max_input_channels']} ch, "
                        f"{dev['default_samplerate']} Hz)",
                        err=True,
                    )
        except Exception:
            pass
        sys.exit(1)

    # Flatten and convert
    audio = recording.flatten().astype(np.float64)

    # Process in chunks
    chunk_size = int(sample_rate * chunk_duration)
    total_samples = 0
    samples_buffer: list[tuple[float, float, float]] = []

    import time as _time

    for i in range(n_chunks):
        start = i * chunk_size
        end = start + chunk_size
        chunk = audio[start:end]

        leq = process_chunk(chunk, sample_rate)
        lpeak = leq + 6.0  # conservative peak estimate
        ts = _time.time()

        samples_buffer.append((ts, leq, lpeak))

        if len(samples_buffer) >= 10:
            db.insert_samples(samples_buffer)
            total_samples += len(samples_buffer)
            samples_buffer.clear()

        click.echo(f"  [{ts:.1f}] Leq: {leq:.1f} dB(A)")

    # Flush remaining
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
    devs = sd.query_devices()
    input_devs = [(i, d) for i, d in enumerate(devs) if d["max_input_channels"] > 0]
    if not input_devs:
        click.echo("No input devices found.")
        return

    click.echo("Available audio input devices:")
    for idx, dev in input_devs:
        click.echo(
            f"  [{idx}] {dev['name']} "
            f"({dev['max_input_channels']} ch, "
            f"{dev['default_samplerate']} Hz)"
        )
