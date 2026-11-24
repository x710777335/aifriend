"""WebSocket v1 server for XiaoZhi ESP32 devices.

Incoming raw Opus v1 packets are decoded only after the device sends
``listen/stop``; all expensive work stays off the asyncio event loop.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from companion.config import Settings
from companion.server.conversation import ConversationService
from companion.server.protocol import ProtocolError, decode_control, encode_control, validate_hello
from companion.server.session import DeviceSession, SessionManager, SessionPhase
from companion.server.media import OpusDecoder
from companion.server.segmenter import PcmSegmenter
from companion.server.voice import EdgeTtsOpusSynthesizer, SenseVoiceRecognizer

logger = logging.getLogger(__name__)


class FriendWebSocketServer:
    def __init__(self, settings: Settings, conversation: ConversationService) -> None:
        self._settings = settings
        self._conversation = conversation
        self.sessions = SessionManager()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._recognizer = SenseVoiceRecognizer(settings.asr)
        self._synthesizer = EdgeTtsOpusSynthesizer(settings.tts)

    async def serve_forever(self) -> None:
        from websockets.asyncio.server import serve
        async with serve(self._handle_connection, self._settings.server.host, self._settings.server.port,
                         max_size=1_048_576, ping_interval=20, ping_timeout=20):
            logger.info("ESP32 WebSocket server listening on %s:%s", self._settings.server.host, self._settings.server.port)
            await asyncio.Future()

    @staticmethod
    def _headers(websocket: Any) -> Any:
        request = getattr(websocket, "request", None)
        return request.headers if request is not None else websocket.request_headers

    async def _handle_connection(self, websocket: Any) -> None:
        headers = self._headers(websocket)
        device_id = headers.get("Device-Id", "")
        configured_token = self._settings.server.device_token
        if configured_token and headers.get("Authorization") != f"Bearer {configured_token}":
            await websocket.close(code=4401, reason="unauthorized")
            return
        try:
            session = self.sessions.open(device_id)
        except ValueError:
            await websocket.close(code=4400, reason="missing Device-Id")
            return
        logger.info("Device connected: %s (%s)", session.device_id, session.session_id)
        try:
            async for raw in websocket:
                if isinstance(raw, bytes):
                    await self._handle_audio(websocket, session, raw)
                else:
                    await self._handle_control(websocket, session, raw)
        except ProtocolError as exc:
            await self._send_error(websocket, session, str(exc))
        except Exception:
            logger.exception("Unhandled device connection error: %s", session.device_id)
        finally:
            await self._cancel_turn(session.session_id)
            self.sessions.close(session.session_id)
            logger.info("Device disconnected: %s", session.device_id)

    async def _handle_control(self, websocket: Any, session: DeviceSession, raw: str) -> None:
        message = decode_control(raw)
        kind = message["type"]
        if kind == "hello":
            validate_hello(message)
            await websocket.send(encode_control(
                "hello", session.session_id, transport="websocket",
                audio_params={"format": "opus", "sample_rate": 24000, "channels": 1, "frame_duration": 60},
            ))
            return
        if message.get("session_id") != session.session_id:
            raise ProtocolError("unknown session_id")
        if kind == "listen":
            if message.get("state") == "start":
                await self._cancel_turn(session.session_id)
                session.start_listening()
                session.listen_mode = message.get("mode", "auto")
                session.decoder = OpusDecoder(16000)
                session.segmenter = PcmSegmenter(self._settings.audio)
            elif message.get("state") == "detect":
                return
            elif message.get("state") == "stop":
                pcm = session.segmenter.finish() if session.segmenter else None
                if pcm is not None:
                    self._start_audio_turn(websocket, session, pcm)
                elif session.phase == SessionPhase.LISTENING:
                    session.phase = SessionPhase.CONNECTED
            else:
                raise ProtocolError("listen state must be start or stop")
            return
        if kind == "abort":
            session.abort()
            await self._cancel_turn(session.session_id)
            await websocket.send(encode_control("tts", session.session_id, state="stop"))
            return
        if kind == "stt":
            # Useful only for protocol testing. Production turns originate from decoded Opus.
            if not self._settings.server.allow_test_stt:
                raise ProtocolError("client STT injection disabled")
            text = message.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ProtocolError("stt requires non-empty text")
            await self._start_text_turn(websocket, session, text.strip())
            return
        if kind in {"llm", "tts"}:
            # Device-side acknowledgements are accepted but cannot alter server state.
            return
        raise ProtocolError(f"unsupported control type: {kind}")

    async def _handle_audio(self, websocket: Any, session: DeviceSession, payload: bytes) -> None:
        if session.phase != SessionPhase.LISTENING or session.decoder is None:
            return
        pcm = await asyncio.to_thread(session.decoder.decode_packet, payload)
        segment = session.segmenter.push(pcm, auto_finish=session.listen_mode != "manual")
        if segment is not None:
            self._start_audio_turn(websocket, session, segment)

    def _start_audio_turn(self, websocket: Any, session: DeviceSession, pcm: Any) -> None:
        session.phase = SessionPhase.THINKING
        logger.info("Speech segment ready: device=%s samples=%d", session.device_id, len(pcm))
        task = asyncio.create_task(self._process_audio_turn(websocket, session, session.turn_id, pcm))
        self._tasks[session.session_id] = task

    async def _start_text_turn(self, websocket: Any, session: DeviceSession, text: str) -> None:
        session.phase = SessionPhase.THINKING
        turn_id = session.turn_id
        await websocket.send(encode_control("stt", session.session_id, text=text))
        task = asyncio.create_task(self._complete_text_turn(websocket, session, turn_id, text))
        self._tasks[session.session_id] = task

    async def _complete_text_turn(self, websocket: Any, session: DeviceSession, turn_id: int, text: str) -> None:
        try:
            await websocket.send(encode_control("llm", session.session_id, emotion="friend_thinking"))
            answer = await self._conversation.reply(session.conversation_id, text)
            if session.turn_id != turn_id or session.phase == SessionPhase.ABORTED:
                return
            await self._send_reply_audio(websocket, session, turn_id, answer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Conversation failed for %s", session.device_id)
            await self._send_error(websocket, session, "conversation failed")
            session.phase = SessionPhase.CONNECTED

    async def _process_audio_turn(self, websocket: Any, session: DeviceSession, turn_id: int, pcm: Any) -> None:
        """Decode buffered device audio and feed the shared ASR → LLM → TTS path."""
        try:
            if session.turn_id != turn_id or session.phase == SessionPhase.ABORTED:
                return
            await websocket.send(encode_control("llm", session.session_id, emotion="friend_thinking"))
            text = await asyncio.to_thread(self._recognizer.transcribe, pcm)
            if not text:
                logger.info("No speech recognized for device %s", session.device_id)
                await websocket.send(encode_control("llm", session.session_id, emotion="friend_listening"))
                session.phase = SessionPhase.CONNECTED
                return
            await websocket.send(encode_control("stt", session.session_id, text=text))
            answer = await self._conversation.reply(session.conversation_id, text)
            if session.turn_id != turn_id or session.phase == SessionPhase.ABORTED:
                return
            await self._send_reply_audio(websocket, session, turn_id, answer)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Audio turn failed for %s", session.device_id)
            await self._send_error(websocket, session, "voice processing failed")
            session.phase = SessionPhase.CONNECTED

    async def _send_reply_audio(self, websocket: Any, session: DeviceSession, turn_id: int, answer: str) -> None:
        packets = await self._synthesizer.synthesize(answer) if self._settings.tts.enabled else []
        logger.info("TTS ready: device=%s opus_packets=%d", session.device_id, len(packets))
        if session.turn_id != turn_id or session.phase == SessionPhase.ABORTED:
            return
        await websocket.send(encode_control("llm", session.session_id, emotion="happy", text=""))
        session.phase = SessionPhase.SPEAKING
        await websocket.send(encode_control("tts", session.session_id, state="start"))
        try:
            await websocket.send(encode_control("tts", session.session_id, state="sentence_start", text=answer))
            await asyncio.sleep(0.1)
            for payload in packets:
                if session.turn_id != turn_id or session.phase == SessionPhase.ABORTED:
                    return
                await websocket.send(payload)
                await asyncio.sleep(0.06)
        finally:
            if session.turn_id == turn_id and session.phase != SessionPhase.ABORTED:
                await websocket.send(encode_control("tts", session.session_id, state="stop"))
                session.phase = SessionPhase.CONNECTED

    async def _cancel_turn(self, session_id: str) -> None:
        task = self._tasks.pop(session_id, None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _send_error(self, websocket: Any, session: DeviceSession, message: str) -> None:
        with suppress(Exception):
            await websocket.send(encode_control("error", session.session_id, message=message))
