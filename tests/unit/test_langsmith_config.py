from __future__ import annotations

import os

from app_logging.langsmith import configure_langsmith
from config.settings import get_settings


def _clean_langsmith_env(monkeypatch) -> None:
    keys = [
        "LANGCHAIN_TRACING_V2",
        "LANGCHAIN_ENDPOINT",
        "LANGCHAIN_API_KEY",
        "LANGCHAIN_PROJECT",
        "LANGSMITH_TRACING",
        "LANGSMITH_ENDPOINT",
        "LANGSMITH_API_KEY",
        "LANGSMITH_PROJECT",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_configure_langsmith_sets_both_env_namespaces(monkeypatch) -> None:
    _clean_langsmith_env(monkeypatch)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    monkeypatch.setenv("LANGSMITH_PROJECT", "tp-test")
    get_settings.cache_clear()

    configure_langsmith()

    assert "true" == os.environ["LANGCHAIN_TRACING_V2"]
    assert "true" == os.environ["LANGSMITH_TRACING"]
    assert "test-key" == os.environ["LANGCHAIN_API_KEY"]
    assert "test-key" == os.environ["LANGSMITH_API_KEY"]
    get_settings.cache_clear()


def test_configure_langsmith_disables_and_clears_when_missing_key(monkeypatch) -> None:
    _clean_langsmith_env(monkeypatch)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "should-be-cleared")
    monkeypatch.setenv("LANGSMITH_API_KEY", "should-be-cleared")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    get_settings.cache_clear()

    configure_langsmith()

    assert "false" == os.environ["LANGCHAIN_TRACING_V2"]
    assert "false" == os.environ["LANGSMITH_TRACING"]
    assert "LANGCHAIN_API_KEY" not in os.environ
    assert "LANGSMITH_API_KEY" not in os.environ
    get_settings.cache_clear()


def test_configure_langsmith_fallbacks_endpoint(monkeypatch) -> None:
    _clean_langsmith_env(monkeypatch)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "smith.local")
    get_settings.cache_clear()

    configure_langsmith()

    assert "https://api.smith.langchain.com" == os.environ["LANGCHAIN_ENDPOINT"]
    assert "https://api.smith.langchain.com" == os.environ["LANGSMITH_ENDPOINT"]
    get_settings.cache_clear()
