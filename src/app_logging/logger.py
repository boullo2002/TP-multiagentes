from __future__ import annotations

import logging

from config.settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    level_name = settings.app.environment.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
