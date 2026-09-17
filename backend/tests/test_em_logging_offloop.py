"""2026-09-16 20:37 PT: the loop watch caught a 51.5 s event-loop stall with the main thread inside
logging.FileHandler.emit (the rotating file handler writing from uvicorn's response send). Root logging now goes
through a QueueHandler; the file and console handlers run on a QueueListener thread. The line format is unchanged
and every record still reaches the file."""
import io
import logging
import logging.handlers
import time

from zargar.main import LOG_FORMAT, configure_logging


def test_root_logging_is_queued_and_the_file_still_gets_the_formatted_line(tmp_path):
    saved_handlers = list(logging.getLogger().handlers); saved_level = logging.getLogger().level
    stream = io.StringIO()
    log_path = tmp_path / "zargar-test.log"
    listener = configure_logging(log_path, stream=stream)
    try:
        root = logging.getLogger()
        assert len(root.handlers) == 1 and isinstance(root.handlers[0], logging.handlers.QueueHandler), "the loop only enqueues"
        assert all(not isinstance(h, logging.FileHandler) for h in root.handlers), "no file handler on the loop's path"
        logging.getLogger("zargar.test").warning("hello %s", "queue")
        for _ in range(50):                       # the listener thread drains asynchronously
            if log_path.exists() and "hello queue" in log_path.read_text(encoding="utf-8"):
                break
            time.sleep(0.02)
    finally:
        listener.stop()
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
    text = log_path.read_text(encoding="utf-8")
    assert "WARNING zargar.test hello queue" in text, text
    line = [ln for ln in text.splitlines() if "hello queue" in ln][0]
    assert line[:4].isdigit() and line.count("hello queue") == 1, "asctime prefix present, formatted exactly once (no double formatting)"
    assert "hello queue" in stream.getvalue()
    assert LOG_FORMAT.startswith("%(asctime)s")
