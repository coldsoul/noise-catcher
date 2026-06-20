"""Audio capture using the sounddevice library.

Handles opening the microphone, recording audio chunks, and yielding
them for downstream processing.
"""

from collections.abc import Generator
from typing import Any

import numpy as np
import sounddevice as sd


class AudioCapture:
    """Captures audio from a microphone using sounddevice (PortAudio)."""

    def __init__(
        self,
        device: str | int | None = None,
        sample_rate: int = 48000,
        channels: int = 1,
        blocksize: int = 0,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self._stream: sd.InputStream | None = None

    def record_blocking(self, duration_s: float) -> np.ndarray:
        """Record audio for a fixed duration synchronously.

        Args:
            duration_s: Recording duration in seconds.

        Returns:
            1D float32 array of audio samples.
        """
        n_samples = int(self.sample_rate * duration_s)
        recording = sd.rec(
            n_samples,
            samplerate=self.sample_rate,
            channels=self.channels,
            device=self.device,
            dtype="float32",
        )
        sd.wait()
        if self.channels == 1:
            return recording.flatten().astype(np.float64)
        return recording.astype(np.float64)

    def record_stream(self, chunk_duration_s: float = 1.0) -> Generator[np.ndarray, None, None]:
        """Yield audio chunks in a streaming fashion.

        Opens the stream once and yields chunks until the generator is closed.
        Each chunk is chunk_duration_s seconds long.

        Args:
            chunk_duration_s: Duration of each yielded chunk in seconds.

        Yields:
            1D float64 arrays of audio samples.
        """
        chunk_size = int(self.sample_rate * chunk_duration_s)
        buffer: list[np.ndarray] = []

        def callback(indata: np.ndarray, frames: int, time: Any, status: Any) -> None:
            if status:
                import sys

                print(f"Audio callback status: {status}", file=sys.stderr)
            buffer.append(indata.copy())

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            device=self.device,
            dtype="float32",
            blocksize=chunk_size,
            callback=callback,
        ):
            while True:
                # Wait until we have at least chunk_size samples
                accumulated = sum(len(chunk) for chunk in buffer)
                if accumulated >= chunk_size:
                    # Concatenate and yield exactly chunk_size samples
                    combined = np.concatenate(buffer)
                    chunk = combined[:chunk_size].flatten().astype(np.float64)
                    # Keep remainder
                    remainder = combined[chunk_size:]
                    buffer.clear()
                    if len(remainder) > 0:
                        buffer.append(remainder)
                    yield chunk
                else:
                    sd.sleep(int(chunk_duration_s * 500))  # sleep half a chunk

    def list_devices(self) -> list[dict[str, Any]]:
        """Return list of available audio input devices."""
        devices = sd.query_devices()
        result = []
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                result.append(
                    {
                        "index": i,
                        "name": dev["name"],
                        "channels": dev["max_input_channels"],
                        "default_samplerate": dev["default_samplerate"],
                    }
                )
        return result
