"""Digital signal processing: A-weighting filter, RMS, and dB conversion.

A-weighting (IEC 61672) approximates the human ear's frequency response.
For environmental noise measurement, dB(A) is the standard metric used by
regulations worldwide.
"""

import math

import numpy as np
from scipy.signal import bilinear_zpk, sosfilt, zpk2sos

# Reference sound pressure in Pascals (threshold of human hearing)
REFERENCE_PRESSURE = 20e-6  # 20 µPa


def _build_a_weighting_sos(sample_rate: int) -> np.ndarray:
    """Build raw (un-normalized) A-weighting SOS filter.

    Bilinear transform of the analog prototype:
        H(s) = s^4 / ((s+ω1)^2 * (s+ω4)^2)
    where ω1 = 2π·20.6, ω4 = 2π·12194 (IEC 61672-1).
    """
    w1 = 2.0 * math.pi * 20.598997
    w4 = 2.0 * math.pi * 12194.217

    zeros = [0.0, 0.0, 0.0, 0.0]
    poles = [-w1, -w1, -w4, -w4]

    z, p, k_d = bilinear_zpk(zeros, poles, 1.0, sample_rate)
    return zpk2sos(z, p, k_d)


def _measure_gain_at_1khz(sos: np.ndarray, sample_rate: int) -> float:
    """Measure the actual gain of an SOS filter at 1 kHz."""
    dur = max(0.05, 10.0 / sample_rate)  # enough cycles for measurement
    n = int(sample_rate * dur)
    t = np.arange(n) / sample_rate
    test_signal = np.sin(2.0 * math.pi * 1000.0 * t)
    filtered = sosfilt(sos, test_signal)
    rms_in = float(np.sqrt(np.mean(test_signal**2)))
    rms_out = float(np.sqrt(np.mean(filtered**2)))
    return rms_out / rms_in if rms_in > 0 else 1.0


# Pre-compute filter and gain for 48 kHz
_A_WEIGHTING_SOS_48K_RAW = _build_a_weighting_sos(48000)
_A_WEIGHTING_GAIN_48K = _measure_gain_at_1khz(_A_WEIGHTING_SOS_48K_RAW, 48000)

# Cache for other sample rates
_a_weighting_cache: dict[int, tuple[np.ndarray, float]] = {}


def _get_a_weighting_filter(sample_rate: int) -> tuple[np.ndarray, float]:
    """Get (sos, gain_correction) tuple, computing and caching if needed."""
    if sample_rate == 48000:
        return _A_WEIGHTING_SOS_48K_RAW, _A_WEIGHTING_GAIN_48K

    if sample_rate not in _a_weighting_cache:
        sos = _build_a_weighting_sos(sample_rate)
        gain = _measure_gain_at_1khz(sos, sample_rate)
        _a_weighting_cache[sample_rate] = (sos, gain)

    return _a_weighting_cache[sample_rate]


def apply_a_weighting(samples: np.ndarray, sample_rate: int = 48000) -> np.ndarray:
    """Apply A-weighting filter to audio samples.

    Args:
        samples: Audio samples, 1D or 2D (channels, samples). Float32 or float64.
        sample_rate: Sample rate in Hz. Must be >= 8000.

    Returns:
        A-weighted samples as float64 with same shape as input.
        Normalized so gain at 1 kHz = 1.0 (0 dB).
    """
    if sample_rate < 8000:
        raise ValueError(f"Sample rate must be >= 8000 Hz, got {sample_rate}")

    sos, gain = _get_a_weighting_filter(sample_rate)
    samples_f64 = np.asarray(samples, dtype=np.float64)

    if samples_f64.ndim == 1:
        result = sosfilt(sos, samples_f64)
    elif samples_f64.ndim == 2:
        result = np.empty_like(samples_f64)
        for ch in range(samples_f64.shape[0]):
            result[ch] = sosfilt(sos, samples_f64[ch])
    else:
        raise ValueError(f"Expected 1D or 2D array, got {samples_f64.ndim}D")

    # Compensate for the filter's inherent gain at 1 kHz
    if gain > 0:
        result /= gain

    return result


def compute_rms(samples: np.ndarray) -> float:
    """Compute RMS (root mean square) of audio samples.

    Args:
        samples: 1D array of audio samples.

    Returns:
        RMS value as float. Zero for empty or all-zero input.
    """
    samples = np.asarray(samples, dtype=np.float64)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples**2)))


def rms_to_db(rms: float, ref: float = REFERENCE_PRESSURE) -> float:
    """Convert RMS pressure to dB SPL.

    Args:
        rms: RMS value in Pascals (after calibration applied).
        ref: Reference pressure (default 20 µPa for dB SPL).

    Returns:
        Sound pressure level in dB. Returns -inf for zero input.
    """
    if rms <= 0.0:
        return float("-inf")
    return float(20.0 * np.log10(rms / ref))


def process_chunk(samples: np.ndarray, sample_rate: int = 48000) -> float:
    """Compute dB(A) level for a chunk of audio samples.

    Convenience function that chains: A-weighting → RMS → dB.

    Note: This returns dB relative to full-scale digital unless the samples
    have been scaled to Pascals via microphone calibration.

    Args:
        samples: 1D array of audio samples (float32/float64 PCM).
        sample_rate: Sample rate in Hz.

    Returns:
        dB value (digital dBFS before calibration, dB SPL after).
    """
    weighted = apply_a_weighting(samples, sample_rate)
    rms = compute_rms(weighted)
    return rms_to_db(rms, ref=1.0)  # ref=1.0 → dBFS (full-scale)


def sine_wave(
    frequency: float,
    sample_rate: int,
    duration: float,
    amplitude: float = 1.0,
) -> np.ndarray:
    """Generate a sine wave for testing.

    Args:
        frequency: Frequency in Hz.
        sample_rate: Sample rate in Hz.
        duration: Duration in seconds.
        amplitude: Peak amplitude (0.0 to 1.0).

    Returns:
        1D float64 array of samples.
    """
    n_samples = int(sample_rate * duration)
    t = np.arange(n_samples) / sample_rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * t)).astype(np.float64)
