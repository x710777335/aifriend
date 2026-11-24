import tempfile
import unittest
from pathlib import Path

from companion.server.protocol import ProtocolError, decode_control, validate_hello
from companion.server.session import SessionManager, SessionPhase
from companion.storage import ChatRepository


class EspProtocolTests(unittest.TestCase):
    def test_hello_requires_xiaozhi_v1_opus_parameters(self) -> None:
        message = decode_control(
            '{"type":"hello","version":1,"transport":"websocket",'
            '"audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}}'
        )
        self.assertEqual(validate_hello(message)["sample_rate"], 16000)
        message["version"] = 2
        with self.assertRaises(ProtocolError):
            validate_hello(message)

    def test_session_audio_and_turns_are_isolated(self) -> None:
        manager = SessionManager()
        first, second = manager.open("AA:BB"), manager.open("CC:DD")
        self.assertNotEqual(first.conversation_id, second.conversation_id)
        first.start_listening()
        first.append_opus(b"opus-a")
        self.assertEqual(first.opus_frames, [b"opus-a"])
        self.assertEqual(second.opus_frames, [])
        first.abort()
        self.assertEqual(first.phase, SessionPhase.ABORTED)
        self.assertEqual(first.opus_frames, [])

    def test_repository_keeps_esp32_histories_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ChatRepository(Path(directory) / "history.sqlite3")
            repository.add_message("user", "first", "esp32:one")
            repository.add_message("user", "second", "esp32:two")
            self.assertEqual(repository.recent_messages(2, "esp32:one"), [{"role": "user", "content": "first"}])
            self.assertEqual(repository.recent_messages(2, "esp32:two"), [{"role": "user", "content": "second"}])
            repository.close()


if __name__ == "__main__":
    unittest.main()
