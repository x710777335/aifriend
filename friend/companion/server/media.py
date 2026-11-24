"""PyAV-backed Opus/PCM conversion for XiaoZhi WebSocket protocol v1."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np


class MediaError(RuntimeError):
    pass


def _av():
    try:
        import av
        return av
    except ImportError as exc:
        raise MediaError("PyAV is required for ESP32 Opus audio; run: python -m pip install av") from exc


class OpusDecoder:
    """A stateful decoder for raw XiaoZhi WebSocket v1 Opus packets."""
    def __init__(self, sample_rate: int = 16000) -> None:
        av = _av()
        self.sample_rate = sample_rate
        self._codec = av.CodecContext.create("opus", "r")
        self._codec.sample_rate = sample_rate
        self._codec.layout = "mono"
        self._codec.open()
        self._resampler = av.audio.resampler.AudioResampler(format="fltp", layout="mono", rate=sample_rate)

    def decode_packet(self, payload: bytes) -> np.ndarray:
        av = _av()
        chunks = []
        for frame in self._codec.decode(av.Packet(payload)):
            for converted in self._resampler.resample(frame):
                chunks.append(np.asarray(converted.to_ndarray()[0], dtype=np.float32))
        return np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)

    def decode(self, packets: Iterable[bytes]) -> np.ndarray:
        av = _av()
        chunks: list[np.ndarray] = []
        try:
            for payload in packets:
                chunks.append(self.decode_packet(payload))
            for frame in self._codec.decode(None):
                for converted in self._resampler.resample(frame):
                    chunks.append(np.asarray(converted.to_ndarray()[0], dtype=np.float32))
            for converted in self._resampler.resample(None):
                chunks.append(np.asarray(converted.to_ndarray()[0], dtype=np.float32))
        except Exception as exc:
            raise MediaError(f"failed to decode Opus stream: {exc}") from exc
        return np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)


class OpusEncoder:
    """Encode mono float PCM into individual raw Opus payloads."""
    def __init__(self, sample_rate: int = 24000, bitrate: int = 24000) -> None:
        av = _av()
        self.sample_rate = sample_rate
        self._codec = av.CodecContext.create("libopus", "w")
        self._codec.sample_rate = sample_rate
        self._codec.layout = "mono"
        self._codec.format = "fltp"
        self._codec.bit_rate = bitrate
        self._codec.options = {"frame_duration": "60"}
        self._codec.open()

    def encode_pcm(self, pcm: np.ndarray, input_rate: int) -> list[bytes]:
        av = _av()
        pcm = np.asarray(pcm, dtype=np.float32).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(pcm, format="flt", layout="mono")
        frame.sample_rate = input_rate
        resampler = av.audio.resampler.AudioResampler(format="fltp", layout="mono", rate=self.sample_rate)
        output_frames = resampler.resample(frame)
        packets: list[bytes] = []
        try:
            for output in output_frames:
                packets.extend(bytes(packet) for packet in self._codec.encode(output))
            packets.extend(bytes(packet) for packet in self._codec.encode(None))
        except Exception as exc:
            raise MediaError(f"failed to encode Opus stream: {exc}") from exc
        return packets


def decode_audio_file(path: Path, target_rate: int = 24000) -> np.ndarray:
    """Decode Edge TTS MP3 and resample it to the ESP32 output rate."""
    av = _av()
    chunks: list[np.ndarray] = []
    try:
        with av.open(str(path)) as container:
            resampler = av.audio.resampler.AudioResampler(format="flt", layout="mono", rate=target_rate)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    chunks.append(np.asarray(converted.to_ndarray()[0], dtype=np.float32))
    except Exception as exc:
        raise MediaError(f"failed to decode TTS audio: {exc}") from exc
    if not chunks:
        raise MediaError("TTS generated no audio frames")
    return np.concatenate(chunks)
