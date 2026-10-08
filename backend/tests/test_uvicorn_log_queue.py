"""2026-10-08: a 3.7 s event-loop stall sat in logging.StreamHandler.emit - uvicorn's default log config attached
synchronous console handlers to its own loggers. The entrypoint must hand uvicorn log_config=None so every line goes
through the root QueueHandler (written on the listener thread)."""
import io
import logging
import logging.handlers

from zargar import main as main_mod


def test_uvicorn_is_started_without_its_own_log_config(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(main_mod, "configure_logging", lambda p: type("L", (), {"stop": lambda self: None})())
    monkeypatch.setattr(main_mod, "create_app", lambda cfg: object())
    monkeypatch.setattr(main_mod.uvicorn, "run", lambda app, **kw: seen.update(kw))
    main_mod.main()
    assert "log_config" in seen and seen["log_config"] is None


def test_uvicorn_loggers_reach_the_root_queue(tmp_path):
    out = io.StringIO()
    listener = main_mod.configure_logging(tmp_path / "t.log", stream=out)
    try:
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            lg = logging.getLogger(name)
            assert not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.QueueHandler)
                           for h in lg.handlers), name
            assert lg.propagate, name
        logging.getLogger("uvicorn.access").info("GET /api/health 200")
    finally:
        listener.stop()
    assert "GET /api/health 200" in out.getvalue()
