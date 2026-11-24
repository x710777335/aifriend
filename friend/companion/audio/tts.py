"""Asynchronous Edge TTS synthesis adapter."""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from companion.config import TtsSettings

logger = logging.getLogger(__name__)


def text_for_speech(text: str) -> str:
    """Remove Markdown punctuation from the spoken channel.

    The chat transcript stays untouched; this normalization is only applied
    before synthesis so headings/emphasis are spoken naturally.
    """
    return text.replace("#", "").replace("*", "")


class TtsWorker(QThread):
    succeeded = Signal(str, int)
    failed = Signal(str, int)

    def __init__(self, text: str, settings: TtsSettings, session_id: int) -> None:
        super().__init__()
        self._text, self._settings, self._session_id = text, settings, session_id

    def run(self) -> None:
        try:
            import edge_tts
            fd, filename = tempfile.mkstemp(prefix="companion_tts_", suffix=".mp3")
            # Close the descriptor created by mkstemp before the async writer opens it on Windows.
            import os
            os.close(fd)
            Path(filename).unlink(missing_ok=True)  # edge-tts needs to create the output itself.
            asyncio.run(edge_tts.Communicate(
                text_for_speech(self._text), voice=self._settings.voice,
                rate=self._settings.rate, volume=self._settings.volume
            ).save(filename))
            self.succeeded.emit(filename, self._session_id)
        except Exception as exc:
            logger.exception("TTS synthesis failed")
            self.failed.emit(f"语音合成失败：{exc}", self._session_id)
