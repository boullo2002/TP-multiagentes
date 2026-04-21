from __future__ import annotations

import logging
import os

from config.settings import get_settings

logger = logging.getLogger(__name__)

_ENV_TRUE = "true"
_ENV_FALSE = "false"
_LANGCHAIN_KEYS = (
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_ENDPOINT",
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_PROJECT",
)
_LANGSMITH_KEYS = (
    "LANGSMITH_TRACING",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
)


def _set_env(key: str, value: str) -> None:
    os.environ[key] = value


def _clear_optional_env(keys: tuple[str, ...]) -> None:
    for key in keys:
        os.environ.pop(key, None)


def configure_langsmith() -> None:
    settings = get_settings()
    tracing_requested = bool(settings.langsmith.tracing)
    endpoint = (settings.langsmith.endpoint or "").strip() or "https://api.smith.langchain.com"
    api_key = (settings.langsmith.api_key or "").strip()
    project = (settings.langsmith.project or "").strip() or "tp-multiagentes"

    if tracing_requested and not api_key:
        logger.warning(
            "langsmith_tracing_disabled_missing_key",
            extra={"event": "langsmith_tracing_disabled_missing_key"},
        )

    if tracing_requested and not endpoint.startswith(("http://", "https://")):
        logger.warning(
            "langsmith_invalid_endpoint_fallback endpoint=%s",
            endpoint,
            extra={"event": "langsmith_invalid_endpoint_fallback"},
        )
        endpoint = "https://api.smith.langchain.com"

    enabled = tracing_requested and bool(api_key)
    _set_env("LANGCHAIN_TRACING_V2", _ENV_TRUE if enabled else _ENV_FALSE)
    _set_env("LANGSMITH_TRACING", _ENV_TRUE if enabled else _ENV_FALSE)
    if not enabled:
        _clear_optional_env(_LANGCHAIN_KEYS[1:])
        _clear_optional_env(_LANGSMITH_KEYS[1:])
        return

    _set_env("LANGCHAIN_ENDPOINT", endpoint)
    _set_env("LANGCHAIN_API_KEY", api_key)
    _set_env("LANGCHAIN_PROJECT", project)
    _set_env("LANGSMITH_ENDPOINT", endpoint)
    _set_env("LANGSMITH_API_KEY", api_key)
    _set_env("LANGSMITH_PROJECT", project)
