"""Silero-first VAD segmenter with deterministic energy fallback."""
from __future__ import annotations

import collections
import logging
import queue
import threading
from typing import Callable

import numpy as np
from PySide6.QtCore import QThread, Signal

from companion.config import AudioSettings

logger = logging.getLogger(__name__)


class SpeechSegmenter:
    def __init__(self, settings: AudioSettings) -> None:
        self.settings = settings
        self._prebuffer: collections.deque[np.ndarray] = collections.deque()
        self._speech: list[np.ndarray] = []
        self._active = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._silero: Callable[[np.ndarray, int], float] | None = self._load_silero()

    def _load_silero(self) -> Callable[[np.ndarray, int], float] | None:
        try:
            import torch
            model, _utils = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
            model.reset_states()

            def probability(frame: np.ndarray, sample_rate: int) -> float:
                """Silero's model API accepts 512 samples (32 ms at 16 kHz).

                Do not call get_speech_timestamps here: it is a *whole recording*
                segmenter with its own 250ms minimum, so it always rejects one
                microphone frame and prevents ASR from ever being triggered.
                """
                samples = torch.from_numpy(np.ascontiguousarray(frame)).float()
                return float(model(samples, sample_rate).item())

            logger.info("Silero VAD loaded")
            return probability
        except Exception:
            logger.warning("Silero VAD unavailable; using local energy fallback", exc_info=True)
            return None

    def _is_speech(self, frame: np.ndarray) -> bool:
        if self._silero:
            try:
                return self._silero(frame, self.settings.sample_rate) >= 0.5
            except Exception:
                logger.warning("Silero frame inference failed; falling back to energy", exc_info=True)
        return float(np.sqrt(np.mean(np.square(frame)))) > 0.012

    def push(self, frame: np.ndarray) -> tuple[str | None, np.ndarray | None]:
        duration_ms = len(frame) * 1000 / self.settings.sample_rate
        max_pre_frames = max(1, int(self.settings.vad_prebuffer_ms / duration_ms))
        self._prebuffer.append(frame)
        while len(self._prebuffer) > max_pre_frames:
            self._prebuffer.popleft()
        speech = self._is_speech(frame)
        if not self._active:
            if speech:
                self._speech_frames += 1
                if self._speech_frames * duration_ms >= self.settings.vad_start_ms:
                    self._active = True
                    self._speech = list(self._prebuffer)
                    self._silence_frames = 0
                    return "started", None
            else:
                self._speech_frames = 0
            return None, None
        self._speech.append(frame)
        if speech:
            self._silence_frames = 0
        else:
            self._silence_frames += 1
        elapsed_ms = sum(len(item) for item in self._speech) * 1000 / self.settings.sample_rate
        ended = self._silence_frames * duration_ms >= self.settings.vad_silence_ms
        timed_out = elapsed_ms >= self.settings.vad_max_speech_s * 1000
        if not (ended or timed_out):
            return None, None
        data = np.concatenate(self._speech)
        self._active, self._speech, self._speech_frames, self._silence_frames = False, [], 0, 0
        if len(data) * 1000 / self.settings.sample_rate < self.settings.vad_min_speech_ms:
            return "ended", None
        return "segment", data


class VadWorker(QThread):
    speech_started = Signal()
    speech_ended = Signal()
    segment_ready = Signal(object)  # numpy float32 audio
    failed = Signal(str)

    def __init__(self, frame_queue: queue.Queue[np.ndarray], settings: AudioSettings) -> None:
        super().__init__()
        self._queue, self._settings = frame_queue, settings
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            segmenter = SpeechSegmenter(self._settings)
            while not self._stop.is_set():
                try:
                    event, segment = segmenter.push(self._queue.get(timeout=0.15))
                except queue.Empty:
                    continue
                if event == "started": self.speech_started.emit()
                elif event in {"ended", "segment"}: self.speech_ended.emit()
                if segment is not None: self.segment_ready.emit(segment)
        except Exception as exc:
            logger.exception("VAD worker failed")
            self.failed.emit(str(exc))
