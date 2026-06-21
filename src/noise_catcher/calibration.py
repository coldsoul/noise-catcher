"""Microphone calibration pipeline for UMIK-1 calibration files.

Parses miniDSP UMIK-1 .cal files and provides functions to convert
raw dBFS measurements to calibrated dB SPL values.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# UMIK-1 nominal sensitivity: at 94 dB SPL (1 Pa), the digital output
# is approximately -18 dBFS. This is configurable for different gain
# settings or microphone models.
SENSITIVITY_DBFS_AT_94DB = 18.0


@dataclass
class CalibrationData:
    """Holds frequency response correction data from a UMIK-1 calibration file.

    Attributes:
        frequencies: List of frequency points in Hz.
        sens_factors: List of sensitivity correction values in dB.
            Positive means the microphone under-reports at that frequency
            (needs positive gain correction).
    """

    frequencies: list[float]
    sens_factors: list[float]

    def sens_factor_at(self, frequency: float) -> float:
        """Get the SensFactor at a given frequency via linear interpolation.

        Args:
            frequency: Target frequency in Hz.

        Returns:
            Interpolated sensitivity correction in dB.
            Returns 0.0 if no calibration data is available.
        """
        if len(self.frequencies) == 0:
            return 0.0
        return float(np.interp(frequency, self.frequencies, self.sens_factors))


def load_calibration(filepath: str) -> CalibrationData:
    """Parse a miniDSP UMIK-1 .cal calibration file.

    The file format::

        # miniDSP UMIK-1 Calibration File
        # Serial: 700-XXXX
        # Format: Freq(Hz)  SensFactor(dB)  Phase(deg)
        20.0    -0.17    0.00
        25.0    -0.27    0.00
        ...

    Comment lines (starting with ``#``) and empty lines are ignored.
    Data lines must have at least two whitespace-separated columns:
    frequency (Hz) and sensitivity correction (dB). An optional third
    column (phase in degrees) is ignored.

    Args:
        filepath: Path to the .cal file.

    Returns:
        CalibrationData with frequencies and sensitivity corrections.

    Raises:
        FileNotFoundError: If the calibration file does not exist.
    """
    frequencies: list[float] = []
    sens_factors: list[float] = []

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            try:
                freq = float(parts[0])
                sens = float(parts[1])
                frequencies.append(freq)
                sens_factors.append(sens)
            except ValueError:
                # Skip malformed lines
                continue

    return CalibrationData(frequencies=frequencies, sens_factors=sens_factors)


def apply_calibration(
    samples: np.ndarray,
    cal: CalibrationData,
    sample_rate: int,
) -> np.ndarray:
    """Apply frequency-dependent gain correction via FFT.

    Uses the calibration frequency response to apply per-bin correction
    in the frequency domain. The correction is smooth (slowly varying
    with frequency), so spectral leakage is not a practical concern and
    no windowing is applied.

    For real-time use, pre-compute the per-bin gain factors and apply
    them via overlap-add processing on buffered audio.

    Args:
        samples: 1D array of audio samples.
        cal: Calibration data with frequency response corrections.
        sample_rate: Sample rate in Hz.

    Returns:
        Calibrated samples with same shape and dtype as input.
    """
    samples_in = np.asarray(samples, dtype=np.float64)
    n = len(samples_in)

    if n < 2:
        return samples_in.copy()

    # Forward FFT
    spectrum = np.fft.rfft(samples_in)
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)

    # Interpolate correction factors for each frequency bin
    corrections = np.interp(freqs, cal.frequencies, cal.sens_factors)

    # Convert dB corrections to linear amplitude gain
    # A +3 dB correction → gain of ~1.41 (amplitude multiplied by sqrt(2))
    gain = 10.0 ** (corrections / 20.0)

    # Apply per-bin gain correction
    spectrum *= gain

    # Inverse FFT
    corrected = np.fft.irfft(spectrum, n=n)

    return corrected.astype(samples.dtype)


def db_to_spl(
    db_value: float,
    cal: CalibrationData | None = None,
) -> float:
    """Convert dBFS to dB SPL using microphone calibration.

    The conversion uses the formula::

        dB_SPL = dBFS - sens_factor_1kHz + 94 + SENSITIVITY_DBFS_AT_94DB

    Where:
        * ``sens_factor_1kHz`` is the SensFactor interpolated at 1 kHz
          (or 0.0 if no calibration is provided).
        * ``SENSITIVITY_DBFS_AT_94DB`` is the nominal digital level at
          94 dB SPL (default 18.0, i.e. -18 dBFS = 94 dB SPL).

    Args:
        db_value: dBFS value to convert.
        cal: Optional calibration data. If provided, uses the SensFactor
            at 1 kHz for frequency correction.

    Returns:
        Calibrated dB SPL value.
    """
    sens_factor = 0.0
    if cal is not None:
        sens_factor = cal.sens_factor_at(1000.0)
    return db_value - sens_factor + 94.0 + SENSITIVITY_DBFS_AT_94DB
