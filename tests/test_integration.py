"""Integration test: synthetic sine wave → dB(A) → storage → graph.

End-to-end test that exercises the entire pipeline without requiring
a real microphone.
"""

import os
import tempfile

from noise_catcher.dsp import process_chunk, sine_wave
from noise_catcher.graph import render_daily_graph
from noise_catcher.storage import NoiseDB


def test_end_to_end_pipeline() -> None:
    """Synthetic audio → dB(A) → SQLite → rendered PNG."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_file:
        db_path = db_file.name
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
        output_path = img_file.name

    try:
        # 1. Create synthetic 60 seconds of audio (mixed frequencies)
        db = NoiseDB(db_path)
        db.initialize()

        sample_rate = 48000
        # Simulate background noise: 40 dB SPL equivalent at varying levels
        for second in range(60):
            # Generate a second of audio with some variation
            freq = 200 + (second % 10) * 50  # varying frequency
            amplitude = 0.001 * (1.0 + (second % 5) * 0.2)  # varying amplitude
            chunk = sine_wave(freq, sample_rate, 1.0, amplitude)
            # Add some "traffic" noise at specific seconds
            if 20 <= second <= 25:
                chunk += sine_wave(80, sample_rate, 1.0, amplitude * 3)

            leq = process_chunk(chunk, sample_rate)
            # Store with a fake timestamp
            ts = float(second)
            db.insert_sample(ts, leq, leq + 6.0)  # lpeak = leq + 6 dB (typical)

        db.close()

        # 2. Verify data was stored
        db2 = NoiseDB(db_path)
        db2.initialize()
        count = db2.count_samples()
        assert count == 60, f"Expected 60 samples, got {count}"
        db2.close()

        # 3. Render the graph (using a fake date in epoch)
        result = render_daily_graph(db_path, output_path=output_path)
        assert os.path.exists(result)
        assert os.path.getsize(result) > 0

    finally:
        os.unlink(db_path)
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_empty_to_graph_no_error() -> None:
    """Empty database → graph should produce a 'no data' image without error."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        output_path = f.name

    try:
        result = render_daily_graph(":memory:", output_path=output_path)
        assert os.path.exists(result)
        assert os.path.getsize(result) > 0
    finally:
        os.unlink(output_path)
