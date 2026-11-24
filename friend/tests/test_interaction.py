import unittest

from companion.interaction import AvatarState, InteractionManager


class InteractionManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = InteractionManager()

    def test_message_lifecycle(self) -> None:
        self.assertEqual(self.manager.dispatch("user_message_sent"), AvatarState.THINKING)
        self.assertEqual(self.manager.dispatch("assistant_response_ready"), AvatarState.SPEAKING)
        self.assertEqual(self.manager.dispatch("speech_finished"), AvatarState.IDLE)

    def test_unknown_event_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.dispatch("not_an_event")

    def test_state_signal_only_emits_on_change(self) -> None:
        observed = []
        self.manager.state_changed.connect(observed.append)
        self.manager.dispatch("speech_finished")
        self.manager.dispatch("user_started_input")
        self.assertEqual(observed, [AvatarState.LISTENING])


if __name__ == "__main__":
    unittest.main()
