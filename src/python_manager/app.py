"""Application entry point."""

from __future__ import annotations

import sys


def _log_unhandled(exc_type, exc, tb) -> None:
    from .core import logs

    logs.get().critical("Unhandled exception", exc_info=(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if "--version" in argv[1:]:
        from . import __version__

        print(f"Python Manager {__version__}")
        return 0
    self_test = "--self-test" in argv[1:]

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .core import config, logs
    from .ui import theme
    from .ui.main_window import MainWindow

    logs.setup()
    sys.excepthook = _log_unhandled
    app = QApplication(argv)
    app.setApplicationName("Python Manager")
    app.setOrganizationName("PythonManager")
    theme.apply(config.get("theme"), app)
    window = MainWindow()
    window.show()
    if self_test:
        # Start up, run the event loop once and exit: checks that a release build works.
        # exit() rather than quit(), which would ask whether to cancel the startup tasks.
        QTimer.singleShot(0, lambda: app.exit(0))
    code = app.exec()
    # Stop the worker threads and delete the window while the QApplication still exists;
    # otherwise both are torn down at interpreter exit in no particular order, which can crash.
    window.tasks.shutdown()
    del window
    return code


if __name__ == "__main__":
    raise SystemExit(main())
