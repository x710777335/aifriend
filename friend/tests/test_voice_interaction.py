import unittest

from companion.interaction import AvatarState, ConversationState, InteractionManager


class VoiceInteractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = InteractionManager()

    def test_half_duplex_lifecycle(self) -> None:
        events = [
            "voice_enabled", "speech_started", "speech_segment_ready", "asr_completed",
            "llm_response_for_voice", "tts_synthesizing", "tts_ready", "playback_finished",
        ]
        for event in events:
            self.manager.dispatch(event)
        self.assertEqual(self.manager.state, AvatarState.LISTENING)
        self.assertEqual(self.manager.conversation_state, ConversationState.LISTENING)

    def test_disable_recovers_to_idle(self) -> None:
        self.manager.dispatch("voice_enabled")
        self.manager.dispatch("voice_disabled")
        self.assertEqual(self.manager.state, AvatarState.IDLE)
        self.assertEqual(self.manager.conversation_state, ConversationState.IDLE)
