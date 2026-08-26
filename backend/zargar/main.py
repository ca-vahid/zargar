"""Entrypoint: python -m zargar.main"""
from __future__ import annotations

import logging
import logging.handlers
import pathlib

import uvicorn

from .api.app import create_app
from .config import get_config


def main() -> None:
    config = get_config()
    # Always keep a rotating file log next to the package: the app usually runs
    # detached/hidden on Windows, and the 2026-08-25 feed outage was
    # undiagnosable because stdout went to a hidden window and nothing else.
    log_path = pathlib.Path(__file__).resolve().parent.parent / f"zargar-{config.port}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), file_handler],
    )
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
