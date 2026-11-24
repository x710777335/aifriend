"""Lazy local FunASR SenseVoice adapter."""
from __future__ import annotations

import logging
import re

import numpy as np
from PySide6.QtCore import QThread, Signal

from companion.config import AsrSettings

logger = logging.getLogger(__name__)
_TAG = re.compile(r"<[^>]+>|\[[^\]]+\]")


class AsrWorker(QThread):
    succeeded = Signal(str, int)
    failed = Signal(str, int)

    def __init__(self, audio: np.ndarray, sample_rate: int, settings: AsrSettings, session_id: int) -> None:
        super().__init__()
        self._audio, self._sample_rate, self._settings, self._session_id = audio, sample_rate, settings, session_id

    def run(self) -> None:
        try:
            from funasr import AutoModel
            model = AutoModel(model=self._settings.model, device=self._settings.device, disable_update=True)
            result = model.generate(input=self._audio, cache={}, language=self._settings.language, use_itn=True)
            text = "" if not result else str(result[0].get("text", ""))
            text = _TAG.sub("", text).strip()
            self.succeeded.emit(text, self._session_id)
        except Exception as exc:
            logger.exception("ASR failed")
            self.failed.emit(f"语音识别失败：{exc}", self._session_id)
