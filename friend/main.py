"""Application entry point."""
import sys

from PySide6.QtWidgets import QApplication

from companion.config import configure_logging, load_settings
from companion.storage import ChatRepository
from companion.ui.main_window import MainWindow


def main() -> int:
    settings = load_settings()
    configure_logging(settings.log_path)
    app = QApplication(sys.argv)
    app.setApplicationName("AI Virtual Companion")
    repository = ChatRepository(settings.database_path)
    window = MainWindow(settings, repository)
    window.show()
    exit_code = app.exec()
    repository.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
