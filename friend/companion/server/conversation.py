"""Shared LLM and persistence path for ESP32 conversations, without Qt."""
from __future__ import annotations

import asyncio

from companion.config import Settings
from companion.llm import LLMService
from companion.storage import ChatRepository


class ConversationService:
    def __init__(self, settings: Settings, repository: ChatRepository) -> None:
        self._settings = settings
        self._repository = repository
        self._llm = LLMService(settings)

    async def reply(self, conversation_id: str, text: str) -> str:
        """Persist a device-scoped turn then make the blocking provider call off-loop."""
        self._repository.add_message("user", text, conversation_id)
        messages = self._repository.recent_messages(self._settings.context_turns * 2, conversation_id)
        answer = await asyncio.to_thread(self._llm.reply, messages)
        self._repository.add_message("assistant", answer, conversation_id)
        return answer
