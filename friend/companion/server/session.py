"""Per-device live sessions and cancellation tokens."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class SessionPhase(str, Enum):
    CONNECTED = "connected"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ABORTED = "aborted"


@dataclass
class DeviceSession:
    device_id: str
    session_id: str = field(default_factory=lambda: uuid4().hex)
    phase: SessionPhase = SessionPhase.CONNECTED
    turn_id: int = 0
    opus_frames: list[bytes] = field(default_factory=list)
    decoder: object | None = None
    segmenter: object | None = None
    listen_mode: str = "auto"

    @property
    def conversation_id(self) -> str:
        return f"esp32:{self.device_id}"

    def start_listening(self) -> int:
        self.turn_id += 1
        self.phase = SessionPhase.LISTENING
        self.opus_frames.clear()
        return self.turn_id

    def abort(self) -> int:
        self.turn_id += 1
        self.phase = SessionPhase.ABORTED
        self.opus_frames.clear()
        return self.turn_id

    def append_opus(self, frame: bytes, maximum_frames: int = 512) -> None:
        if self.phase != SessionPhase.LISTENING:
            return
        if len(self.opus_frames) >= maximum_frames:
            # 512 × 60 ms bounds a server-side stalled stream at about 31 seconds.
            self.opus_frames.pop(0)
        self.opus_frames.append(frame)


class SessionManager:
    """The only owner of active ESP32 sessions; histories are device-scoped."""
    def __init__(self) -> None:
        self._sessions: dict[str, DeviceSession] = {}

    def open(self, device_id: str) -> DeviceSession:
        if not device_id or len(device_id) > 128:
            raise ValueError("invalid Device-Id")
        session = DeviceSession(device_id=device_id)
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> DeviceSession | None:
        return self._sessions.get(session_id)

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
