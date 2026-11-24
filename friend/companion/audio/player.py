"""PCM playback on a worker thread with RMS mouth-animation events."""
from __future__ import annotations

import logging
import os
import threading

import numpy as np
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class AudioPlayer(QThread):
    energy_changed = Signal(float, int)
    completed = Signal(int)
    failed = Signal(str, int)

    def __init__(self, filename: str, session_id: int) -> None:
        super().__init__()
        self._filename, self._session_id = filename, session_id
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            import sounddevice as sd
            import soundfile as sf
            data, rate = sf.read(self._filename, dtype="float32", always_2d=True)
            with sd.OutputStream(samplerate=rate, channels=data.shape[1], dtype="float32") as stream:
                for start in range(0, len(data), 1024):
                    if self._stop.is_set():
                        break
                    chunk = data[start:start + 1024]
                    rms = float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0
                    self.energy_changed.emit(min(1.0, rms * 8.0), self._session_id)
                    stream.write(chunk)
            self.energy_changed.emit(0.0, self._session_id)
            self.completed.emit(self._session_id)
        except Exception as exc:
            logger.exception("Audio playback failed")
            self.failed.emit(f"音频播放失败：{exc}", self._session_id)
        finally:
            try:
                os.unlink(self._filename)
            except OSError:
                pass
