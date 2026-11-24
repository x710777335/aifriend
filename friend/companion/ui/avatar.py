"""State-aware avatar with PNG assets and painted fallbacks."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel

from companion.interaction import AvatarState


class AvatarWidget(QLabel):
    _COLORS = {
        AvatarState.IDLE: "#667eea", AvatarState.GREETING: "#f6ad55",
        AvatarState.LISTENING: "#38b2ac", AvatarState.THINKING: "#9f7aea",
        AvatarState.SPEAKING: "#ed64a6",
    }

    def __init__(self, avatar_dir: Path) -> None:
        super().__init__()
        self._avatar_dir = avatar_dir
        self._state = AvatarState.IDLE
        self._mouth_open = 0.0
        self.setFixedSize(310, 380)
        self.setAlignment(Qt.AlignCenter)
        self.set_state(AvatarState.IDLE)

    def set_state(self, state: AvatarState) -> None:
        self._state = state
        self._mouth_open = 0.0
        path = self._avatar_dir / f"{state.value.lower()}.png"
        pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
        if pixmap.isNull():
            pixmap = self._placeholder(state)
        self.setPixmap(pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.setToolTip(state.value)

    def set_mouth_open(self, value: float) -> None:
        """Animate fallback art from playback RMS; PNG assets remain gracefully static."""
        value = max(0.0, min(1.0, value))
        if abs(value - self._mouth_open) < 0.08:
            return
        self._mouth_open = value
        path = self._avatar_dir / f"{self._state.value.lower()}.png"
        if not path.exists():
            self.setPixmap(self._placeholder(self._state))

    def _placeholder(self, state: AvatarState) -> QPixmap:
        pixmap = QPixmap(self.size())
        pixmap.fill(QColor("#f7fafc"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self._COLORS[state])
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(55, 30, 200, 200)
        painter.setBrush(QColor("#fff"))
        painter.drawEllipse(104, 105, 18, 18)
        painter.drawEllipse(188, 105, 18, 18)
        painter.setPen(QPen(QColor("#fff"), 7, Qt.SolidLine, Qt.RoundCap))
        if self._mouth_open > 0.35:
            painter.setBrush(QColor("#fff"))
            painter.drawEllipse(135, 150, 55, int(10 + 34 * self._mouth_open))
        elif self._mouth_open > 0.08:
            painter.drawLine(139, 166, 188, 166)
        else:
            painter.drawArc(115, 112, 85, 75, 205 * 16, 130 * 16)
        painter.setPen(QColor("#2d3748"))
        painter.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        painter.drawText(pixmap.rect().adjusted(0, 260, 0, 0), Qt.AlignHCenter, state.value)
        painter.end()
        return pixmap
