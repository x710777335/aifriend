import unittest
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np

from companion.config import AudioSettings
from companion.server.media import OpusDecoder, OpusEncoder
from companion.server.segmenter import PcmSegmenter
from companion.server.session import DeviceSession, SessionPhase
from companion.server.websocket_server import FriendWebSocketServer


class EspAudioTests(unittest.TestCase):
    def test_opus_packets_are_60ms_and_decode_at_16khz(self):
        packets = OpusEncoder(24000).encode_pcm(np.zeros(24000, dtype=np.float32), 24000)
        self.assertEqual(len(packets), 17)
        decoder = OpusDecoder(16000)
        samples = sum(len(decoder.decode_packet(packet)) for packet in packets)
        self.assertTrue(16000 <= samples <= 16400)

    def test_end_after_three_seconds_of_silence(self):
        vad = PcmSegmenter(AudioSettings())
        speech = np.full(960, 0.1, dtype=np.float32)
        silence = np.zeros(960, dtype=np.float32)
        for _ in range(10):
            self.assertIsNone(vad.push(speech))
        for _ in range(49):
            self.assertIsNone(vad.push(silence))
        self.assertIsNotNone(vad.push(silence))

    def test_manual_mode_waits_for_stop(self):
        vad = PcmSegmenter(AudioSettings())
        for _ in range(10):
            vad.push(np.full(960, 0.1, dtype=np.float32), auto_finish=False)
        for _ in range(55):
            self.assertIsNone(vad.push(np.zeros(960, dtype=np.float32), auto_finish=False))
        self.assertIsNotNone(vad.finish())


class EspAudioFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_automatic_segment_is_transcribed_and_reply_is_sent(self):
        settings = SimpleNamespace(audio=AudioSettings(), asr=SimpleNamespace(), tts=SimpleNamespace(enabled=True))
        conversation = SimpleNamespace(reply=AsyncMock(return_value="hello"))
        server = FriendWebSocketServer(settings, conversation)
        server._recognizer = SimpleNamespace(transcribe=lambda pcm: "你好")
        server._synthesizer = SimpleNamespace(synthesize=AsyncMock(return_value=[b"opus"]))
        socket = SimpleNamespace(send=AsyncMock())
        session = DeviceSession("test")
        session.start_listening()
        session.decoder = SimpleNamespace(decode_packet=lambda payload: np.frombuffer(payload, dtype=np.float32))
        session.segmenter = PcmSegmenter(settings.audio)
        speech = np.full(960, 0.1, dtype=np.float32).tobytes()
        silence = np.zeros(960, dtype=np.float32).tobytes()
        for _ in range(10):
            await server._handle_audio(socket, session, speech)
        for _ in range(50):
            await server._handle_audio(socket, session, silence)
        self.assertEqual(session.phase, SessionPhase.THINKING)
        await asyncio.wait_for(server._tasks[session.session_id], timeout=3)
        messages = [call.args[0] for call in socket.send.await_args_list]
        self.assertIn(b"opus", messages)
        control = [json.loads(item) for item in messages if isinstance(item, str)]
        self.assertEqual([item["type"] for item in control], ["llm", "stt", "llm", "tts", "tts", "tts"])
        self.assertEqual(control[0]["emotion"], "friend_thinking")
        self.assertEqual(control[-1]["state"], "stop")
