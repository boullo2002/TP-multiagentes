from __future__ import annotations

from memory.user_preferences import (
    effective_response_language,
    normalize_user_preferences,
    prefs_for_prompts,
    user_requested_full_sql_result,
)


def test_normalize_merges_legacy_keys() -> None:
    p = normalize_user_preferences({"language": "en", "output_format": "json"})
    assert p["preferred_language"] == "en"
    assert p["preferred_output_format"] == "json"


def test_prefs_for_prompts_maps_names() -> None:
    p = prefs_for_prompts({"preferred_language": "es", "preferred_output_format": "table"})
    assert p["language"] == "es"
    assert p["output_format"] == "table"
    assert "date_format" in p


def test_user_requested_full_sql_result_phrases() -> None:
    assert user_requested_full_sql_result(user_text="mostrame directo del mcp", prefs=None)
    assert user_requested_full_sql_result(user_text="quiero lo que trajo la bd", prefs=None)


def test_user_requested_full_sql_result_pref_flag() -> None:
    assert user_requested_full_sql_result(user_text="hola", prefs={"full_sql_result": True}) is True


def test_effective_response_language_keeps_spanish_on_short_mixed_query() -> None:
    lang = effective_response_language({"preferred_language": "es"}, "top 10")
    assert lang == "es"
