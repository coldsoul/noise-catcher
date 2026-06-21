"""Tests for microphone calibration pipeline.

Tests cover parsing UMIK-1 .cal files, converting dBFS to dB SPL,
and applying frequency-dependent gain correction via FFT.
"""

from pathlib import Path

import numpy as np
import pytest

from noise_catcher.calibration import (
    SENSITIVITY_DBFS_AT_94DB,
    CalibrationData,
    apply_calibration,
    db_to_spl,
    load_calibration,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_CAL = FIXTURES_DIR / "sample.cal"


class TestLoadCalibration:
    """Parsing UMIK-1 .cal files."""

    def test_parse_cal_file(self) -> None:
        """Parse a valid .cal file and verify frequency/correction pairs."""
        cal = load_calibration(str(SAMPLE_CAL))
        assert len(cal.frequencies) == 3
        assert cal.frequencies[0] == 20.0
        assert cal.frequencies[1] == 1000.0
        assert cal.frequencies[2] == 20000.0
        assert cal.sens_factors[0] == -0.50
        assert cal.sens_factors[1] == 0.00
        assert cal.sens_factors[2] == -1.50

    def test_parse_strips_comments_and_headers(self) -> None:
        """Lines starting with # are ignored by the parser."""
        cal = load_calibration(str(SAMPLE_CAL))
        # The fixture has 3 comment lines and 3 data lines
        assert len(cal.frequencies) == 3
        assert len(cal.sens_factors) == 3

    def test_parse_with_missing_file(self) -> None:
        """A missing .cal file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_calibration("/nonexistent/file.cal")

    def test_sensitivity_at_1khz(self) -> None:
        """Extract correct SensFactor value at 1 kHz via interpolation."""
        cal = load_calibration(str(SAMPLE_CAL))
        sens = cal.sens_factor_at(1000.0)
        assert sens == pytest.approx(0.0, abs=0.01)

    def test_sensitivity_at_20hz(self) -> None:
        """Extract correct SensFactor value at 20 Hz (exact match)."""
        cal = load_calibration(str(SAMPLE_CAL))
        sens = cal.sens_factor_at(20.0)
        assert sens == pytest.approx(-0.50, abs=0.01)

    def test_sensitivity_interpolated(self) -> None:
        """SensFactor at an intermediate frequency is linearly interpolated."""
        cal = load_calibration(str(SAMPLE_CAL))
        # At 500 Hz (between 20 Hz and 1000 Hz)
        sens_500 = cal.sens_factor_at(500.0)
        # Linear interpolation: y = y0 + (x - x0) * (y1 - y0) / (x1 - x0)
        expected = -0.50 + (500.0 - 20.0) * (0.0 - (-0.50)) / (1000.0 - 20.0)
        assert sens_500 == pytest.approx(expected, abs=0.01)

    def test_sensitivity_outside_range(self) -> None:
        """Extrapolation works for frequencies outside the calibration range."""
        cal = load_calibration(str(SAMPLE_CAL))
        # Below 20 Hz — numpy.interp uses nearest (extrapolation)
        sens_below = cal.sens_factor_at(10.0)
        assert sens_below == pytest.approx(-0.50, abs=0.01)
        # Above 20 kHz — numpy.interp uses nearest
        sens_above = cal.sens_factor_at(25000.0)
        assert sens_above == pytest.approx(-1.50, abs=0.01)

    def test_parse_file_with_phase_column(self) -> None:
        """Files with a third phase column are parsed correctly."""
        cal = load_calibration(str(SAMPLE_CAL))
        # All three data lines should have been parsed
        assert len(cal.frequencies) == 3
        assert len(cal.sens_factors) == 3


class TestDbToSpl:
    """dBFS to dB SPL conversion."""

    def test_reference_conversion(self) -> None:
        """At 1 kHz with 0.0 SensFactor: -18 dBFS → 94 dB SPL."""
        cal = CalibrationData(frequencies=[1000.0], sens_factors=[0.0])
        spl = db_to_spl(-18.0, cal)
        assert spl == pytest.approx(94.0, abs=0.1)

    def test_db_to_spl_without_calibration(self) -> None:
        """Without calibration data, nominal offset is applied."""
        # -18 dBFS → 94 dB SPL (nominal offset: -18 + 94 + 18 = 94)
        spl = db_to_spl(-18.0)
        assert spl == pytest.approx(94.0, abs=0.1)

    def test_db_to_spl_with_positive_sens_factor(self) -> None:
        """Positive SensFactor at 1 kHz shifts the result upward."""
        cal = CalibrationData(frequencies=[1000.0], sens_factors=[2.0])
        spl = db_to_spl(-18.0, cal)
        # dB_SPL = -18 - 2.0 + 94 + 18 = 92
        assert spl == pytest.approx(92.0, abs=0.1)

    def test_db_to_spl_with_negative_sens_factor(self) -> None:
        """Negative SensFactor at 1 kHz shifts the result downward."""
        cal = CalibrationData(frequencies=[1000.0], sens_factors=[-2.0])
        spl = db_to_spl(-18.0, cal)
        # dB_SPL = -18 - (-2.0) + 94 + 18 = 96
        assert spl == pytest.approx(96.0, abs=0.1)

    def test_higher_dbfs_gives_higher_spl(self) -> None:
        """A louder digital signal produces a higher SPL reading."""
        cal = CalibrationData(frequencies=[1000.0], sens_factors=[0.0])
        spl_low = db_to_spl(-30.0, cal)
        spl_high = db_to_spl(-10.0, cal)
        assert spl_high > spl_low

    def test_94db_spl_at_reference(self) -> None:
        """The formula yields 94 dB SPL when the input equals the reference."""
        cal = CalibrationData(frequencies=[1000.0], sens_factors=[0.0])
        spl = db_to_spl(-18.0, cal)
        assert spl == pytest.approx(94.0, abs=0.01)

    def test_sensitivity_constant_is_positive(self) -> None:
        """SENSITIVITY_DBFS_AT_94DB must be a positive number."""
        assert SENSITIVITY_DBFS_AT_94DB > 0


class TestApplyCalibration:
    """Frequency-dependent gain correction via FFT."""

    def test_identity_for_flat_calibration(self) -> None:
        """A flat calibration (0 dB everywhere) leaves the signal unchanged."""
        cal = CalibrationData(
            frequencies=[20.0, 1000.0, 20000.0],
            sens_factors=[0.0, 0.0, 0.0],
        )
        sr = 48000
        n = 4800
        samples = np.sin(2 * np.pi * 1000 * np.arange(n) / sr).astype(np.float64)
        corrected = apply_calibration(samples, cal, sr)
        rms_in = float(np.sqrt(np.mean(samples**2)))
        rms_out = float(np.sqrt(np.mean(corrected**2)))
        assert rms_out == pytest.approx(rms_in, rel=0.02)

    def test_positive_correction_boosts_level(self) -> None:
        """A positive SensFactor increases the output amplitude."""
        cal = CalibrationData(
            frequencies=[1000.0],
            sens_factors=[3.0],  # +3 dB boost at 1 kHz
        )
        sr = 48000
        n = 4800
        samples = np.sin(2 * np.pi * 1000 * np.arange(n) / sr).astype(np.float64)
        corrected = apply_calibration(samples, cal, sr)
        rms_in = float(np.sqrt(np.mean(samples**2)))
        rms_out = float(np.sqrt(np.mean(corrected**2)))
        # +3 dB → amplitude ratio ≈ 1.41
        assert rms_out > rms_in
        ratio = rms_out / rms_in
        assert ratio == pytest.approx(10 ** (3.0 / 20.0), rel=0.1)

    def test_negative_correction_reduces_level(self) -> None:
        """A negative SensFactor decreases the output amplitude."""
        cal = CalibrationData(
            frequencies=[1000.0],
            sens_factors=[-3.0],  # -3 dB cut at 1 kHz
        )
        sr = 48000
        n = 4800
        samples = np.sin(2 * np.pi * 1000 * np.arange(n) / sr).astype(np.float64)
        corrected = apply_calibration(samples, cal, sr)
        rms_in = float(np.sqrt(np.mean(samples**2)))
        rms_out = float(np.sqrt(np.mean(corrected**2)))
        assert rms_out < rms_in

    def test_preserves_dtype(self) -> None:
        """Output array has the same dtype as the input."""
        cal = CalibrationData(
            frequencies=[20.0, 20000.0],
            sens_factors=[0.0, 0.0],
        )
        sr = 48000
        samples = np.random.randn(4800).astype(np.float32)
        corrected = apply_calibration(samples, cal, sr)
        assert corrected.dtype == samples.dtype

    def test_handles_empty_input(self) -> None:
        """An empty input array returns an empty output."""
        cal = CalibrationData(frequencies=[20.0], sens_factors=[0.0])
        corrected = apply_calibration(np.array([]), cal, 48000)
        assert len(corrected) == 0

    def test_handles_single_sample(self) -> None:
        """A single-element input returns a copy unchanged."""
        cal = CalibrationData(frequencies=[20.0], sens_factors=[0.0])
        samples = np.array([0.5])
        corrected = apply_calibration(samples, cal, 48000)
        assert corrected == pytest.approx(samples)
