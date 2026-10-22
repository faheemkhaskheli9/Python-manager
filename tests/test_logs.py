import logging

from python_manager.core import logs, paths


def test_setup_writes_to_rotating_file():
    path = logs.setup()
    try:
        assert path.parent == paths.logs_dir()
        assert logs.setup() == path
        handlers = [h for h in logging.getLogger(logs.LOGGER).handlers if getattr(h, "_pm_file", False)]
        assert len(handlers) == 1
        assert handlers[0].maxBytes == logs.MAX_BYTES and handlers[0].backupCount == logs.BACKUPS

        logs.get("tests").info("hello from the test")
        handlers[0].flush()
        text = path.read_text(encoding="utf-8")
        assert "Python Manager" in text and "hello from the test" in text
    finally:
        for h in handlers:
            logging.getLogger(logs.LOGGER).removeHandler(h)
            h.close()
