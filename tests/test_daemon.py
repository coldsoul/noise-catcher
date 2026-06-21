"""Tests for the daemon module — signal handling, DB rotation, and run loop."""

import itertools
import os
import signal
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from noise_catcher.daemon import (
    _handle_signal,
    _rotate_db,
    is_shutdown_requested,
    run_forever,
)


class TestSignalHandling:
    """Signal handler registration and behaviour."""

    def test_handler_sets_shutdown_flag(self) -> None:
        """_handle_signal(SIGTERM, ...) sets the global shutdown flag."""
        from noise_catcher import daemon

        daemon._shutdown_requested = False
        _handle_signal(signal.SIGTERM, None)
        assert daemon._shutdown_requested is True
        daemon._shutdown_requested = False  # reset

    def test_handler_sets_flag_on_sigint(self) -> None:
        """_handle_signal(SIGINT, ...) also sets the flag."""
        from noise_catcher import daemon

        daemon._shutdown_requested = False
        _handle_signal(signal.SIGINT, None)
        assert daemon._shutdown_requested is True
        daemon._shutdown_requested = False

    def test_is_shutdown_requested_reflects_flag(self) -> None:
        """is_shutdown_requested() returns current flag state."""
        from noise_catcher import daemon

        daemon._shutdown_requested = False
        assert is_shutdown_requested() is False
        daemon._shutdown_requested = True
        assert is_shutdown_requested() is True
        daemon._shutdown_requested = False


class TestDBRotation:
    """Database file rotation logic."""

    def test_rotate_db_renames_file(self) -> None:
        """Rotating a DB file creates a timestamped copy; original is gone."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "noise_catcher.db"
            db_path.write_text("fake-sqlite-content")

            rotated = _rotate_db(db_path)

            assert not db_path.exists(), "original should be removed"
            assert os.path.exists(rotated), "rotated file should exist"
            assert "noise_catcher." in Path(rotated).name
            assert rotated.endswith(".db")

    def test_rotate_db_returns_valid_path(self) -> None:
        """Rotated path contains the current date."""
        from datetime import date

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "noise_catcher.db"
            db_path.write_text("content")

            rotated = _rotate_db(db_path)
            rotated_name = Path(rotated).name

            today_str = date.today().isoformat()
            assert today_str in rotated_name
            assert rotated_name.startswith("noise_catcher.")

    def test_rotate_db_multiple_same_day(self) -> None:
        """Multiple rotations on the same day get numbered suffixes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "noise_catcher.db"

            # First rotation
            db_path.write_text("first")
            rotated1 = _rotate_db(db_path)
            assert os.path.exists(rotated1)

            # Second rotation: create a new DB and rotate again
            db_path.write_text("second")
            rotated2 = _rotate_db(db_path)
            assert os.path.exists(rotated2)
            assert rotated2 != rotated1, "numbered variant should differ"

    def test_rotate_db_nonexistent_raises(self) -> None:
        """Rotating a non-existent file raises FileNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "noise_catcher.db"
            with pytest.raises(FileNotFoundError):
                _rotate_db(db_path)

    def test_rotate_db_preserves_content(self) -> None:
        """Rotated file preserves the original database content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "noise_catcher.db"
            db_path.write_text("original-data-123")

            rotated = _rotate_db(db_path)

            with open(rotated) as f:
                content = f.read()
            assert content == "original-data-123"


class TestRunForever:
    """Run loop behaviour under shutdown signal conditions."""

    def make_fake_chunk(self, sample_rate: int = 48000) -> np.ndarray:
        """Create a fake audio chunk matching the expected format."""
        return np.zeros(sample_rate, dtype=np.float64)

    def make_mock_stream(self, daemon_module, chunks: list[np.ndarray] | None = None) -> MagicMock:
        """Return a MagicMock stream that yields chunks until shutdown flag is set.

        The stream cycles through *chunks* indefinitely until
        ``daemon_module._shutdown_requested`` is True, at which point
        subsequent ``next()`` calls raise ``StopIteration``.  This lets
        the outer while-loop exit cleanly when the shutdown signal fires.
        """
        if chunks is None:
            chunks = [self.make_fake_chunk()]
        cycle = itertools.cycle(chunks)
        stream = MagicMock()

        def next_chunk(_):
            if daemon_module._shutdown_requested:
                raise StopIteration()
            return next(cycle)

        stream.__next__ = next_chunk
        return stream

    def test_run_forever_exits_when_flag_set(self) -> None:
        """run_forever exits cleanly when shutdown flag is already set."""
        from noise_catcher import daemon

        stream = self.make_mock_stream(daemon)

        mock_capture = MagicMock()
        mock_capture.record_stream.return_value = stream

        with (
            patch("noise_catcher.daemon.AudioCapture", return_value=mock_capture),
            patch("noise_catcher.daemon.NoiseDB") as mock_db_class,
        ):
            mock_db_instance = MagicMock()
            mock_db_class.return_value = mock_db_instance

            # Flag is set before entering the loop
            daemon._shutdown_requested = True
            try:
                run_forever(
                    db_path=":memory:",
                    duration=86400.0,
                    chunk_duration=1.0,
                    sample_rate=48000,
                )
            finally:
                daemon._shutdown_requested = False

            # DB should NOT be initialized since flag was set before loop
            mock_db_instance.initialize.assert_not_called()
            mock_db_instance.close.assert_not_called()

    def test_run_forever_stops_gracefully_mid_iteration(self) -> None:
        """run_forever stops mid-iteration when shutdown flag is raised."""
        from noise_catcher import daemon

        stream = self.make_mock_stream(daemon)

        mock_capture = MagicMock()
        mock_capture.record_stream.return_value = stream

        with (
            patch("noise_catcher.daemon.AudioCapture", return_value=mock_capture),
            patch("noise_catcher.daemon.NoiseDB") as mock_db_class,
        ):
            mock_db_instance = MagicMock()
            mock_db_class.return_value = mock_db_instance

            daemon._shutdown_requested = False

            # Set flag after small delay (simulates SIGTERM mid-recording)
            def delayed_shutdown():
                time.sleep(0.05)
                daemon._shutdown_requested = True

            shutdown_thread = threading.Thread(target=delayed_shutdown, daemon=True)
            shutdown_thread.start()

            run_forever(
                db_path=":memory:",
                duration=86400.0,
                chunk_duration=1.0,
                sample_rate=48000,
            )

            shutdown_thread.join(timeout=2)

            # DB was initialized and closed cleanly
            mock_db_instance.initialize.assert_called_once()
            mock_db_instance.close.assert_called_once()

    def test_run_forever_initializes_db(self) -> None:
        """run_forever creates and initializes a fresh DB."""
        from noise_catcher import daemon

        stream = self.make_mock_stream(daemon)

        mock_capture = MagicMock()
        mock_capture.record_stream.return_value = stream

        with (
            patch("noise_catcher.daemon.AudioCapture", return_value=mock_capture),
            patch("noise_catcher.daemon.NoiseDB") as mock_db_class,
        ):
            mock_db_instance = MagicMock()
            mock_db_class.return_value = mock_db_instance

            daemon._shutdown_requested = False

            def delayed_shutdown():
                time.sleep(0.05)
                daemon._shutdown_requested = True

            shutdown_thread = threading.Thread(target=delayed_shutdown, daemon=True)
            shutdown_thread.start()

            run_forever(
                db_path="test.db",
                duration=86400.0,
                chunk_duration=1.0,
                sample_rate=48000,
            )

            shutdown_thread.join(timeout=2)
            daemon._shutdown_requested = False

            mock_db_class.assert_called_once_with("test.db")
            mock_db_instance.initialize.assert_called_once()
            mock_db_instance.close.assert_called_once()

    def test_run_forever_flushes_samples_on_shutdown(self) -> None:
        """Samples in buffer are flushed to DB before close on shutdown."""
        from noise_catcher import daemon

        stream = self.make_mock_stream(daemon)

        mock_capture = MagicMock()
        mock_capture.record_stream.return_value = stream

        with (
            patch("noise_catcher.daemon.AudioCapture", return_value=mock_capture),
            patch("noise_catcher.daemon.NoiseDB") as mock_db_class,
        ):
            mock_db_instance = MagicMock()
            mock_db_class.return_value = mock_db_instance

            daemon._shutdown_requested = False

            def delayed_shutdown():
                time.sleep(0.05)
                daemon._shutdown_requested = True

            shutdown_thread = threading.Thread(target=delayed_shutdown, daemon=True)
            shutdown_thread.start()

            run_forever(
                db_path=":memory:",
                duration=86400.0,
                chunk_duration=1.0,
                sample_rate=48000,
            )

            shutdown_thread.join(timeout=2)
            daemon._shutdown_requested = False

            # DB was initialized
            mock_db_instance.initialize.assert_called_once()
            # Samples were flushed to DB (insert_samples called)
            mock_db_instance.insert_samples.assert_called()
            mock_db_instance.close.assert_called_once()
