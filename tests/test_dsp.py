"""Tests for digital signal processing: A-weighting filter, RMS computation, dB conversion."""

import numpy as np
import pytest

from noise_catcher.dsp import (
    REFERENCE_PRESSURE,
    apply_a_weighting,
    compute_rms,
    process_chunk,
    rms_to_db,
    sine_wave,
)


class TestAWeighting:
    """A-weighting filter approximates human ear frequency sensitivity."""

    def test_passes_1khz_unchanged(self) -> None:
        """A-weighting at 1 kHz has ~0 dB gain — the reference point."""
        samples = sine_wave(frequency=1000, sample_rate=48000, duration=0.1)
        filtered = apply_a_weighting(samples, sample_rate=48000)
        # RMS ratio should be close to 1.0 (0 dB deviation)
        ratio = compute_rms(filtered) / compute_rms(samples)
        assert 0.9 < ratio < 1.1, f"Expected ~1.0 gain at 1 kHz, got {ratio:.3f}"

    def test_attenuates_low_frequencies(self) -> None:
        """A-weighting strongly attenuates bass frequencies (e.g. 50 Hz)."""
        samples = sine_wave(frequency=50, sample_rate=48000, duration=0.2)
        filtered = apply_a_weighting(samples, sample_rate=48000)
        ratio = compute_rms(filtered) / compute_rms(samples)
        # At 50 Hz, A-weighting attenuates by ~30 dB → ratio ~0.03
        assert ratio < 0.1, f"Expected strong attenuation at 50 Hz, got {ratio:.3f}"

    def test_preserves_array_shape(self) -> None:
        """Output array has same shape as input."""
        samples = np.random.randn(48000).astype(np.float32)
        filtered = apply_a_weighting(samples, sample_rate=48000)
        assert filtered.shape == samples.shape
        assert filtered.dtype == np.float64

    def test_handles_multi_channel(self) -> None:
        """Applies A-weighting independently to each channel."""
        samples = np.random.randn(2, 4800).astype(np.float32)
        filtered = apply_a_weighting(samples, sample_rate=48000)
        assert filtered.shape == samples.shape


class TestRMS:
    """Root Mean Square computation."""

    def test_sine_wave_rms(self) -> None:
        """RMS of a unity-amplitude sine is 1/sqrt(2) ≈ 0.707."""
        samples = sine_wave(frequency=440, sample_rate=48000, duration=1.0, amplitude=1.0)
        rms = compute_rms(samples)
        expected = 1.0 / np.sqrt(2)
        assert rms == pytest.approx(expected, rel=0.01)

    def test_zero_signal(self) -> None:
        """RMS of silence is zero."""
        rms = compute_rms(np.zeros(48000))
        assert rms == 0.0

    def test_dc_signal(self) -> None:
        """RMS of constant DC equals absolute value."""
        rms = compute_rms(np.full(1000, 0.5))
        assert rms == pytest.approx(0.5, rel=0.001)


class TestDecibelConversion:
    """RMS to dB conversion using standard reference pressure."""

    def test_reference_level_is_zero_db(self) -> None:
        """Signal at reference pressure (20 µPa) = 0 dB."""
        assert rms_to_db(REFERENCE_PRESSURE) == pytest.approx(0.0, abs=0.01)

    def test_94db_calibrator_signal(self) -> None:
        """A 94 dB SPL calibrator produces 1 Pa RMS."""
        rms_1_pa = 1.0  # 94 dB SPL = 1 Pa
        db = rms_to_db(rms_1_pa)
        assert db == pytest.approx(94.0, abs=0.1)

    def test_tenfold_pressure_is_20db(self) -> None:
        """10× pressure = +20 dB."""
        db = rms_to_db(10 * REFERENCE_PRESSURE)
        assert db == pytest.approx(20.0, abs=0.01)

    def test_tenth_pressure_is_minus_20db(self) -> None:
        """0.1× pressure = -20 dB."""
        db = rms_to_db(0.1 * REFERENCE_PRESSURE)
        assert db == pytest.approx(-20.0, abs=0.01)

    def test_zero_input_returns_negative_infinity(self) -> None:
        """dB of silence is -inf."""
        assert rms_to_db(0.0) == float("-inf")


class TestProcessChunk:
    """End-to-end DSP convenience function."""

    def test_1khz_sine_gives_reasonable_db(self) -> None:
        """Full-scale 1 kHz sine → ~ -3 dBFS after A-weighting (unity gain at 1kHz)."""
        samples = sine_wave(frequency=1000, sample_rate=48000, duration=0.1, amplitude=1.0)
        db = process_chunk(samples, sample_rate=48000)
        # Full-scale sine: RMS = 1/√2 ≈ 0.707 → 20*log10(0.707) ≈ -3 dB
        # A-weighting at 1 kHz should be ~0 dB gain
        assert -4.0 < db < -2.0, f"Expected ~ -3 dBFS, got {db:.1f}"

    def test_higher_amplitude_gives_higher_db(self) -> None:
        """Louder signal → higher dB reading."""
        quiet = sine_wave(frequency=1000, sample_rate=48000, duration=0.1, amplitude=0.1)
        loud = sine_wave(frequency=1000, sample_rate=48000, duration=0.1, amplitude=0.5)
        db_quiet = process_chunk(quiet, sample_rate=48000)
        db_loud = process_chunk(loud, sample_rate=48000)
        assert db_loud > db_quiet
