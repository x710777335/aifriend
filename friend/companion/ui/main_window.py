"""Main application window and UI-to-service orchestration."""
from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from companion.config import Settings
from companion.audio.manager import AudioManager
from companion.interaction import AvatarState, ConversationState, InteractionManager
from companion.llm import LLMService, LLMWorker
from companion.storage import ChatRepository
from companion.ui.avatar import AvatarWidget

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, repository: ChatRepository) -> None:
        super().__init__()
        self._settings = settings
        self._repository = repository
        self._interaction = InteractionManager()
        self._worker: LLMWorker | None = None
        self._active_source = "text"
        self._audio = AudioManager(settings)
        self.setWindowTitle("AI 虚拟陪伴机器人 · MVP")
        self.resize(960, 620)
        self.setMinimumSize(760, 500)
        self._build_ui()
        self._interaction.state_changed.connect(self._on_state_changed)
        self._interaction.conversation_state_changed.connect(self._on_conversation_state_changed)
        self._audio.state_event.connect(self._on_audio_event)
        self._audio.transcription_ready.connect(self._on_transcription)
        self._audio.error.connect(self._show_audio_error)
        self._audio.mouth_energy.connect(self.avatar.set_mouth_open)
        self._restore_history()
        QTimer.singleShot(250, lambda: self._interaction.dispatch("app_started"))
        QTimer.singleShot(1500, self._finish_greeting)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(22)

        left = QFrame()
        left.setObjectName("avatarPanel")
        left.setFixedWidth(340)
        left_layout = QVBoxLayout(left)
        left_layout.setAlignment(Qt.AlignCenter)
        self.avatar = AvatarWidget(self._settings.avatar_dir)
        self.state_label = QLabel("Idle")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        left_layout.addWidget(self.avatar)
        left_layout.addWidget(self.state_label)
        self.voice_status = QLabel("Voice: off")
        self.voice_status.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.voice_status)

        right = QFrame()
        right_layout = QVBoxLayout(right)
        title = QLabel("和你的陪伴机器人聊天")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        right_layout.addWidget(title)
        self.messages_layout = QVBoxLayout()
        self.messages_layout.setAlignment(Qt.AlignTop)
        messages_widget = QWidget()
        messages_widget.setLayout(self.messages_layout)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(messages_widget)
        right_layout.addWidget(self.scroll, 1)
        voice_controls = QHBoxLayout()
        self.voice_button = QPushButton("Start voice")
        self.voice_button.setCheckable(True)
        self.voice_button.toggled.connect(self._toggle_voice)
        self.device_combo = QComboBox()
        self.device_combo.addItem("Default microphone", None)
        for device_id, name in self._audio.list_devices():
            self.device_combo.addItem(name, device_id)
        self.tts_check = QCheckBox("Read replies aloud")
        self.tts_check.setChecked(self._settings.tts.enabled)
        voice_controls.addWidget(self.voice_button)
        voice_controls.addWidget(self.device_combo, 1)
        voice_controls.addWidget(self.tts_check)
        right_layout.addLayout(voice_controls)
        self.transcript_label = QLabel("Transcript: —")
        self.transcript_label.setWordWrap(True)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #c53030; padding: 3px;")
        right_layout.addWidget(self.transcript_label)
        right_layout.addWidget(self.error_label)
        input_layout = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入消息，例如：你好")
        self.input.textEdited.connect(self._on_user_typing)
        self.input.returnPressed.connect(self._send_message)
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self._send_message)
        input_layout.addWidget(self.input, 1)
        input_layout.addWidget(self.send_button)
        right_layout.addLayout(input_layout)

        layout.addWidget(left)
        layout.addWidget(right, 1)
        self.setStyleSheet("""
            QMainWindow { background: #edf2f7; } QFrame#avatarPanel { background: white; border-radius: 14px; }
            QFrame { background: white; border-radius: 14px; } QLineEdit { padding: 10px; border: 1px solid #cbd5e0; border-radius: 8px; }
            QPushButton { background: #667eea; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: bold; }
            QPushButton:disabled { background: #a0aec0; }
        """)

    def _restore_history(self) -> None:
        for message in self._repository.recent_messages(self._settings.context_turns * 2):
            self._add_bubble(message["role"], message["content"])

    def _add_bubble(self, role: str, content: str) -> None:
        label = QLabel(("你：" if role == "user" else "陪伴机器人：") + content)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        label.setStyleSheet(
            "background: #ebf8ff; color: #1a365d; border-radius: 9px; padding: 10px; margin: 3px;"
            if role == "user" else "background: #f7fafc; color: #2d3748; border-radius: 9px; padding: 10px; margin: 3px;"
        )
        self.messages_layout.addWidget(label)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def _send_message(self) -> None:
        text = self.input.text().strip()
        self._send_user_message(text, source="text")

    def _send_user_message(self, text: str, source: str) -> None:
        if not text or self._worker is not None:
            return
        if source == "text":
            self.input.clear()
        self._active_source = source
        self._add_bubble("user", text)
        self._repository.add_message("user", text)
        self._interaction.dispatch("user_message_sent")
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        messages = self._repository.recent_messages(self._settings.context_turns * 2)
        self._worker = LLMWorker(LLMService(self._settings), messages)
        self._worker.succeeded.connect(self._on_reply)
        self._worker.failed.connect(self._on_failure)
        self._worker.finished.connect(self._finish_request)
        self._worker.start()

    def _on_user_typing(self, text: str) -> None:
        if text and self._worker is None and self._interaction.state == AvatarState.IDLE:
            self._interaction.dispatch("user_started_input")

    def _toggle_voice(self, enabled: bool) -> None:
        self.error_label.clear()
        if enabled:
            if not self._audio.enable(self.device_combo.currentData()):
                self.voice_button.blockSignals(True)
                self.voice_button.setChecked(False)
                self.voice_button.blockSignals(False)
                return
            self.voice_button.setText("Stop voice")
            self.device_combo.setEnabled(False)
        else:
            self._audio.disable()
            self.voice_button.setText("Start voice")
            self.device_combo.setEnabled(True)

    def _on_audio_event(self, event: str) -> None:
        try:
            self._interaction.dispatch(event)
        except ValueError:
            logger.warning("Unknown audio event: %s", event)

    def _on_transcription(self, text: str) -> None:
        self.transcript_label.setText(f"Transcript: {text}")
        self._send_user_message(text, source="voice")

    def _show_audio_error(self, message: str) -> None:
        self.error_label.setText(message)

    def _finish_greeting(self) -> None:
        # Do not let startup's delayed timer overwrite a live interaction.
        if self._interaction.state == AvatarState.GREETING:
            self._interaction.dispatch("greeting_finished")

    def _on_reply(self, reply: str) -> None:
        self._repository.add_message("assistant", reply)
        self._add_bubble("assistant", reply)
        if self._active_source == "voice" and self._audio.enabled:
            self._interaction.dispatch("llm_response_for_voice")
            if self.tts_check.isChecked():
                self._audio.speak(reply)
            else:
                self._audio.reply_finished_without_speech()
        else:
            self._interaction.dispatch("assistant_response_ready")
            QTimer.singleShot(800, lambda: self._interaction.dispatch("speech_finished"))

    def _on_failure(self, error: str) -> None:
        logger.warning("Showing recoverable LLM error to user: %s", error)
        self._add_bubble("assistant", f"抱歉，这次请求没有成功：{error}")
        self._interaction.dispatch("error")
        if self._active_source == "voice" and self._audio.enabled:
            self._audio.reply_finished_without_speech()

    def _finish_request(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.input.setFocus()

    def _on_state_changed(self, state: AvatarState) -> None:
        self.avatar.set_state(state)
        self.state_label.setText(state.value)

    def _on_conversation_state_changed(self, state: ConversationState) -> None:
        self.voice_status.setText(f"Voice: {state.value}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._audio.disable()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(1500)
        event.accept()
