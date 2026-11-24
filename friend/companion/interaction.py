"""Central state machine for UI, future vision, and audio events."""
from __future__ import annotations

from enum import Enum
from typing import Final

from PySide6.QtCore import QObject, Signal


class AvatarState(str, Enum):
    IDLE = "Idle"
    GREETING = "Greeting"
    LISTENING = "Listening"
    THINKING = "Thinking"
    SPEAKING = "Speaking"


class ConversationState(str, Enum):
    """Detailed state for UI and the half-duplex voice pipeline."""
    IDLE = "Idle"
    GREETING = "Greeting"
    LISTENING = "Listening"
    PROCESSING_ASR = "Processing ASR"
    THINKING = "Thinking"
    SYNTHESIZING = "Synthesizing speech"
    SPEAKING = "Speaking"


EVENT_TO_STATE: Final[dict[str, AvatarState]] = {
    "app_started": AvatarState.GREETING,
    "greeting_finished": AvatarState.IDLE,
    "user_started_input": AvatarState.LISTENING,
    "user_message_sent": AvatarState.THINKING,
    "assistant_response_ready": AvatarState.SPEAKING,
    "speech_finished": AvatarState.IDLE,
    "interaction_cancelled": AvatarState.IDLE,
    "error": AvatarState.IDLE,
    "voice_enabled": AvatarState.LISTENING,
    "speech_started": AvatarState.LISTENING,
    "speech_ended": AvatarState.LISTENING,
    "speech_segment_ready": AvatarState.THINKING,
    "asr_completed": AvatarState.THINKING,
    "llm_response_for_voice": AvatarState.THINKING,
    "tts_synthesizing": AvatarState.THINKING,
    "tts_ready": AvatarState.SPEAKING,
    "playback_finished": AvatarState.LISTENING,
    "voice_disabled": AvatarState.IDLE,
}

EVENT_TO_CONVERSATION: Final[dict[str, ConversationState]] = {
    "app_started": ConversationState.GREETING, "greeting_finished": ConversationState.IDLE,
    "user_started_input": ConversationState.LISTENING, "user_message_sent": ConversationState.THINKING,
    "assistant_response_ready": ConversationState.SPEAKING, "speech_finished": ConversationState.IDLE,
    "interaction_cancelled": ConversationState.IDLE, "error": ConversationState.IDLE,
    "voice_enabled": ConversationState.LISTENING, "speech_started": ConversationState.LISTENING,
    "speech_ended": ConversationState.LISTENING,
    "speech_segment_ready": ConversationState.PROCESSING_ASR, "asr_completed": ConversationState.THINKING,
    "llm_response_for_voice": ConversationState.SYNTHESIZING,
    "tts_synthesizing": ConversationState.SYNTHESIZING, "tts_ready": ConversationState.SPEAKING,
    "playback_finished": ConversationState.LISTENING, "voice_disabled": ConversationState.IDLE,
}


class InteractionManager(QObject):
    """Single source of truth for companion state changes."""

    state_changed = Signal(AvatarState)
    conversation_state_changed = Signal(ConversationState)

    def __init__(self) -> None:
        super().__init__()
        self._state = AvatarState.IDLE
        self._conversation_state = ConversationState.IDLE

    @property
    def state(self) -> AvatarState:
        return self._state

    @property
    def conversation_state(self) -> ConversationState:
        return self._conversation_state

    def dispatch(self, event: str) -> AvatarState:
        """Accept events from UI now and vision/audio adapters later."""
        try:
            new_state = EVENT_TO_STATE[event]
        except KeyError as exc:
            raise ValueError(f"Unknown interaction event: {event}") from exc
        if new_state != self._state:
            self._state = new_state
            self.state_changed.emit(new_state)
        conversation_state = EVENT_TO_CONVERSATION[event]
        if conversation_state != self._conversation_state:
            self._conversation_state = conversation_state
            self.conversation_state_changed.emit(conversation_state)
        return self._state
