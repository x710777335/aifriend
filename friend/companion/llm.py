"""LLM service and a QThread worker so requests never block the UI."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QThread, Signal

from companion.config import Settings

logger = logging.getLogger(__name__)
SYSTEM_PROMPT = "你是一位温暖、简洁的桌面虚拟陪伴机器人。请用中文自然回应。"


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def reply(self, messages: list[dict[str, str]]) -> str:
        if self.settings.use_mock_llm:
            time.sleep(0.7)  # Demonstrates a non-blocking request in the MVP.
            latest = messages[-1]["content"] if messages else ""
            return f"你好！我收到了：{latest}。很高兴陪你聊聊。"
        if not self.settings.api_key:
            raise RuntimeError("未设置 OPENAI_API_KEY；或将 USE_MOCK_LLM=true 用于演示模式。")
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.api_key, base_url=self.settings.base_url)
        completion = client.chat.completions.create(
            model=self.settings.model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        )
        content = completion.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned an empty response")
        return content


class LLMWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, service: LLMService, messages: list[dict[str, str]]) -> None:
        super().__init__()
        self._service = service
        self._messages = messages

    def run(self) -> None:
        try:
            self.succeeded.emit(self._service.reply(self._messages))
        except Exception as exc:  # UI must recover from a provider/network failure.
            logger.exception("LLM request failed")
            self.failed.emit(str(exc))
