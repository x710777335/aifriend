"""Minimal, validated XiaoZhi WebSocket v1 message adapter."""
from __future__ import annotations

import json
from typing import Any


class ProtocolError(ValueError):
    pass


def decode_control(raw: str) -> dict[str, Any]:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid JSON control message") from exc
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("control message requires string type")
    return message


def encode_control(message_type: str, session_id: str, **fields: Any) -> str:
    return json.dumps({"type": message_type, "session_id": session_id, **fields}, ensure_ascii=False)


def validate_hello(message: dict[str, Any]) -> dict[str, int | str]:
    if message.get("transport") != "websocket":
        raise ProtocolError("only websocket transport is supported")
    params = message.get("audio_params", {})
    if not isinstance(params, dict) or params.get("format") != "opus":
        raise ProtocolError("only opus audio_params are supported")
    sample_rate = params.get("sample_rate", 16000)
    channels = params.get("channels", 1)
    frame_duration = params.get("frame_duration", 60)
    if sample_rate != 16000 or channels != 1 or frame_duration not in {20, 40, 60}:
        raise ProtocolError("unsupported client audio parameters")
    version = message.get("version", 1)
    if version != 1:
        raise ProtocolError("only WebSocket binary protocol version 1 is enabled")
    return {"sample_rate": sample_rate, "channels": channels, "frame_duration": frame_duration}
