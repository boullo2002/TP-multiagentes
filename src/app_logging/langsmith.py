from __future__ import annotations

import os

from config.settings import get_settings


def configure_langsmith() -> None:
    settings = get_settings()
    if settings.langsmith.tracing and settings.langsmith.api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith.endpoint
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith.api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith.project
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
