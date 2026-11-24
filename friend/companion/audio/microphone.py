"""Non-blocking microphone capture backed by sounddevice."""
from __future__ import annotations

import logging
import queue
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class MicrophoneService:
    """Owns exactly one input stream and exposes a thread-safe PCM queue."""

    def __init__(self, sample_rate: int, channels: int = 1, blocksize: int = 512) -> None:
        self.sample_rate, self.channels, self.blocksize = sample_rate, channels, blocksize
        self.frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=128)
        self._stream: Any | None = None
        self._paused = False

    @staticmethod
    def devices() -> list[tuple[int, str]]:
        try:
            import sounddevice as sd
            return [(i, str(item["name"])) for i, item in enumerate(sd.query_devices()) if item["max_input_channels"] > 0]
        except Exception:
            logger.exception("Unable to enumerate input devices")
            return []

    def start(self, device: int | str | None = None) -> None:
        if self._stream is not None:
            return
        try:
            import sounddevice as sd
            selected = None if device in (None, "", "default") else device
            self._stream = sd.InputStream(
                samplerate=self.sample_rate, channels=self.channels, dtype="float32",
                blocksize=self.blocksize, device=selected, callback=self._callback,
            )
            self._stream.start()
            self._paused = False
        except Exception as exc:
            self._stream = None
            raise RuntimeError(f"无法打开麦克风：{exc}") from exc

    def _callback(self, indata: np.ndarray, frames: int, time_info: object, status: object) -> None:
        if status:
            logger.warning("Microphone status: %s", status)
        if self._paused:
            return
        mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
        try:
            self.frames.put_nowait(mono)
        except queue.Full:
            # Retain realtime behaviour under load instead of stalling the audio callback.
            try:
                self.frames.get_nowait()
                self.frames.put_nowait(mono)
            except queue.Empty:
                pass

    def pause(self) -> None:
        self._paused = True
        self.clear()

    def resume(self) -> None:
        self.clear()
        self._paused = False

    def clear(self) -> None:
        while not self.frames.empty():
            try:
                self.frames.get_nowait()
            except queue.Empty:
                break

    def stop(self) -> None:
        self._paused = True
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.exception("Failed closing microphone stream")
            finally:
                self._stream = None
        self.clear()
