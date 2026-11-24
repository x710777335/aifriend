"""Run the headless ESP32 WebSocket service (no PySide6 GUI required)."""
from __future__ import annotations

import asyncio

from companion.config import configure_logging, load_settings
from companion.server.conversation import ConversationService
from companion.server.websocket_server import FriendWebSocketServer
from companion.storage import ChatRepository


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_path)
    repository = ChatRepository(settings.database_path)
    try:
        await FriendWebSocketServer(settings, ConversationService(settings, repository)).serve_forever()
    finally:
        repository.close()


if __name__ == "__main__":
    asyncio.run(run())
