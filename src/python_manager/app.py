"""Application entry point."""

from __future__ import annotations

import sys


def _log_unhandled(exc_type, exc, tb) -> None:
    from .core import logs

    logs.get().critical("Unhandled exception", exc_info=(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .core import config, logs
    from .ui import theme
    from .ui.main_window import MainWindow

    logs.setup()
    sys.excepthook = _log_unhandled
    app = QApplication(sys.argv)
    app.setApplicationName("Python Manager")
    app.setOrganizationName("PythonManager")
    theme.apply(config.get("theme"), app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
