"""Entrypoint: python -m zargar.main"""
from __future__ import annotations

import logging

import uvicorn

from .api.app import create_app
from .config import get_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    config = get_config()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
