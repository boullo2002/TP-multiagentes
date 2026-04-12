from __future__ import annotations

from memory.user_preferences import normalize_user_preferences, prefs_for_prompts


def test_normalize_merges_legacy_keys() -> None:
    p = normalize_user_preferences({"language": "en", "output_format": "json"})
    assert p["preferred_language"] == "en"
    assert p["preferred_output_format"] == "json"


def test_prefs_for_prompts_maps_names() -> None:
    p = prefs_for_prompts({"preferred_language": "es", "preferred_output_format": "table"})
    assert p["language"] == "es"
    assert p["output_format"] == "table"
    assert "date_format" in p
