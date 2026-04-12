from __future__ import annotations

from memory.persistent_store import PersistentStore
from memory.schema_descriptions_store import SchemaDescriptionsStore
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


def test_schema_descriptions_version_and_timestamp(tmp_data_dir) -> None:
    # Given: store de descripciones
    path = f"{tmp_data_dir}/schema_descriptions.json"
    sd = SchemaDescriptionsStore(PersistentStore(path))
    # When: aprobamos un borrador con tablas
    sd.save_approved({"tables": {"film": {"desc": "películas"}}, "version": 3})
    # Then: hay version y generated_at
    data = sd.load()
    assert data["version"] == 3
    assert data["approved_by_human"] is True
    assert "generated_at" in data
    assert "film" in data["tables"]


def test_session_store_set_get() -> None:
    # Given
    s = SessionStore()
    # When
    s.set("sess-1", "short_term", {"last_sql": "SELECT 1"})
    # Then
    assert s.get("sess-1")["short_term"]["last_sql"] == "SELECT 1"
