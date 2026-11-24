"""Headless ASR and TTS adapters reused by the ESP32 server."""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

import numpy as np

from companion.audio.tts import text_for_speech
from companion.config import AsrSettings, TtsSettings
from companion.server.media import OpusEncoder, decode_audio_file

_TAG = re.compile(r"<[^>]+>|\[[^\]]+\]")


class SenseVoiceRecognizer:
    """Loads SenseVoice once per server process, rather than once per turn."""
    def __init__(self, settings: AsrSettings) -> None:
        self._settings = settings
        self._model = None

    def transcribe(self, pcm: np.ndarray) -> str:
        if not len(pcm):
            return ""
        if self._model is None:
            from funasr import AutoModel
            self._model = AutoModel(model=self._settings.model, device=self._settings.device, disable_update=True)
        result = self._model.generate(input=pcm, cache={}, language=self._settings.language, use_itn=True)
        text = "" if not result else str(result[0].get("text", ""))
        return _TAG.sub("", text).strip()


class EdgeTtsOpusSynthesizer:
    def __init__(self, settings: TtsSettings, output_rate: int = 24000) -> None:
        self._settings, self._output_rate = settings, output_rate

    async def synthesize(self, text: str) -> list[bytes]:
        import edge_tts
        descriptor, filename = tempfile.mkstemp(prefix="friend_esp_tts_", suffix=".mp3")
        os.close(descriptor)
        path = Path(filename)
        try:
            await edge_tts.Communicate(
                text_for_speech(text), voice=self._settings.voice,
                rate=self._settings.rate, volume=self._settings.volume,
            ).save(str(path))
            pcm = await asyncio.to_thread(decode_audio_file, path, self._output_rate)
            return await asyncio.to_thread(OpusEncoder(self._output_rate).encode_pcm, pcm, self._output_rate)
        finally:
            path.unlink(missing_ok=True)
