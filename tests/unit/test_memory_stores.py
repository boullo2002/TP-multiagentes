from __future__ import annotations

from memory.persistent_store import PersistentStore
from memory.schema_context_store import SchemaContextStore
from memory.session_store import SessionStore


def test_persistent_preferences_read_write(tmp_data_dir) -> None:
    # Given: archivo JSON vacío
    path = f"{tmp_data_dir}/user_preferences.json"
    store = PersistentStore(path)
    assert store.load() == {}
    # When: guardamos preferencias
    store.save({"preferred_language": "en", "preferred_output_format": "json"})
    # Then: se leen igual
    assert store.load()["preferred_language"] == "en"


def test_schema_context_version_and_timestamp(tmp_data_dir) -> None:
    # Given: store de contexto
    path = f"{tmp_data_dir}/schema_context.json"
    sc = SchemaContextStore(PersistentStore(path))
    # When: guardamos contexto aprobado
    sc.save(context_markdown="Tablas: film, rental.", version=3)
    # Then
    data = sc.load()
    assert data["version"] == 3
    assert data["approved_by_human"] is True
    assert "generated_at" in data
    assert "context_markdown" in data


def test_session_store_set_get() -> None:
    # Given
    s = SessionStore()
    # When
    s.set("sess-1", "short_term", {"last_sql": "SELECT 1"})
    # Then
    assert s.get("sess-1")["short_term"]["last_sql"] == "SELECT 1"
