"""Coordinates one half-duplex voice session without touching widgets."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from companion.audio.asr import AsrWorker
from companion.audio.microphone import MicrophoneService
from companion.audio.player import AudioPlayer
from companion.audio.tts import TtsWorker
from companion.audio.vad import VadWorker
from companion.config import Settings

logger = logging.getLogger(__name__)


class AudioManager(QObject):
    """Session-token guarded audio pipeline: microphone → VAD → ASR → GUI/LLM → TTS → playback."""
    state_event = Signal(str)
    transcription_ready = Signal(str)
    error = Signal(str)
    mouth_energy = Signal(float)
    devices_changed = Signal(object)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.enabled = False
        self._session_id = 0
        self._microphone: MicrophoneService | None = None
        self._vad: VadWorker | None = None
        self._asr: AsrWorker | None = None
        self._tts: TtsWorker | None = None
        self._player: AudioPlayer | None = None

    def list_devices(self) -> list[tuple[int, str]]:
        devices = MicrophoneService.devices()
        self.devices_changed.emit(devices)
        return devices

    def enable(self, device: int | str | None = None) -> bool:
        if self.enabled:
            return True
        self._session_id += 1
        try:
            self._microphone = MicrophoneService(self.settings.audio.sample_rate, self.settings.audio.channels)
            self._microphone.start(device)
            self._vad = VadWorker(self._microphone.frames, self.settings.audio)
            self._vad.speech_started.connect(lambda: self._emit_if_active("speech_started"))
            self._vad.speech_ended.connect(lambda: self._emit_if_active("speech_ended"))
            self._vad.segment_ready.connect(self._on_segment)
            self._vad.failed.connect(self._on_background_error)
            self._vad.start()
            self.enabled = True
            self.state_event.emit("voice_enabled")
            return True
        except Exception as exc:
            self._cleanup_microphone()
            self.error.emit(str(exc))
            return False

    def disable(self) -> None:
        self.enabled = False
        self._session_id += 1  # All outstanding callbacks become stale.
        for worker in (self._vad, self._asr, self._tts, self._player):
            if worker is not None and hasattr(worker, "stop"):
                worker.stop()
        self._cleanup_microphone()
        self.mouth_energy.emit(0.0)
        self.state_event.emit("voice_disabled")

    def _cleanup_microphone(self) -> None:
        if self._vad is not None:
            self._vad.stop()
            self._vad.wait(1200)
            self._vad.deleteLater()
            self._vad = None
        if self._microphone is not None:
            self._microphone.stop()
            self._microphone = None

    def _emit_if_active(self, event: str) -> None:
        if self.enabled:
            self.state_event.emit(event)

    def _on_segment(self, audio: np.ndarray) -> None:
        if not self.enabled or self._asr is not None:
            return
        session = self._session_id
        # Half-duplex: do not start a second ASR/LLM turn while this turn is pending.
        if self._microphone:
            self._microphone.pause()
        self.state_event.emit("speech_segment_ready")
        self._asr = AsrWorker(audio, self.settings.audio.sample_rate, self.settings.asr, session)
        self._asr.succeeded.connect(self._on_asr_success)
        self._asr.failed.connect(self._on_asr_failure)
        self._asr.finished.connect(self._clear_asr)
        self._asr.start()

    def _clear_asr(self) -> None:
        if self._asr:
            self._asr.deleteLater()
            self._asr = None

    def _on_asr_success(self, text: str, session: int) -> None:
        if not self.enabled or session != self._session_id:
            return
        if not text:
            self._resume_listening()
            return
        self.state_event.emit("asr_completed")
        self.transcription_ready.emit(text)

    def _on_asr_failure(self, message: str, session: int) -> None:
        if self.enabled and session == self._session_id:
            self._on_background_error(message)
            self._resume_listening()

    def reply_finished_without_speech(self) -> None:
        """Recover listening when TTS is switched off or unavailable."""
        if self.enabled:
            self._resume_listening()

    def speak(self, text: str) -> None:
        """Called by the UI only for a reply originating from an active voice turn."""
        if not self.enabled or not self.settings.tts.enabled:
            return
        if self._microphone and self.settings.interaction.ignore_microphone_during_tts:
            self._microphone.pause()
        session = self._session_id
        self.state_event.emit("tts_synthesizing")
        self._tts = TtsWorker(text, self.settings.tts, session)
        self._tts.succeeded.connect(self._on_tts_success)
        self._tts.failed.connect(self._on_tts_failure)
        self._tts.finished.connect(self._clear_tts)
        self._tts.start()

    def _clear_tts(self) -> None:
        if self._tts:
            self._tts.deleteLater()
            self._tts = None

    def _on_tts_success(self, filename: str, session: int) -> None:
        if not self.enabled or session != self._session_id:
            Path(filename).unlink(missing_ok=True)
            return
        self.state_event.emit("tts_ready")
        self._player = AudioPlayer(filename, session)
        self._player.energy_changed.connect(self._on_energy)
        self._player.completed.connect(self._on_playback_finished)
        self._player.failed.connect(self._on_playback_failed)
        self._player.finished.connect(self._clear_player)
        self._player.start()

    def _clear_player(self) -> None:
        if self._player:
            self._player.deleteLater()
            self._player = None

    def _on_tts_failure(self, message: str, session: int) -> None:
        if self.enabled and session == self._session_id:
            self._on_background_error(message)
            self._resume_listening()

    def _on_energy(self, value: float, session: int) -> None:
        if self.enabled and session == self._session_id:
            self.mouth_energy.emit(value)

    def _on_playback_finished(self, session: int) -> None:
        if self.enabled and session == self._session_id:
            self._resume_listening()

    def _on_playback_failed(self, message: str, session: int) -> None:
        if self.enabled and session == self._session_id:
            self._on_background_error(message)
            self._resume_listening()

    def _resume_listening(self) -> None:
        self.mouth_energy.emit(0.0)
        if self._microphone:
            self._microphone.resume()
        if self.settings.interaction.auto_listen_after_reply:
            self.state_event.emit("playback_finished")

    def _on_background_error(self, message: str) -> None:
        logger.warning("Recoverable audio error: %s", message)
        self.error.emit(message)
