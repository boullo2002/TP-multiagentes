from __future__ import annotations

import re
from typing import Any

from memory.persistent_store import PersistentStore

# spec-memory.md §1.1 (valores fijos por defecto; strict/limit se alinean con env al normalizar)
DEFAULT_USER_PREFERENCES: dict[str, Any] = {
    "preferred_language": "es",
    "preferred_output_format": "table",
    "preferred_date_format": "YYYY-MM-DD",
    "sql_safety_strictness": "strict",
    "default_limit": 50,
}


def _coerce_pref_dict(base: dict[str, Any]) -> dict[str, Any]:
    fmt = base.get("preferred_output_format", "table")
    if fmt not in ("table", "json"):
        base["preferred_output_format"] = "table"
    strict = base.get("sql_safety_strictness", "strict")
    if strict not in ("strict", "balanced"):
        base["sql_safety_strictness"] = "strict"
    try:
        base["default_limit"] = max(1, min(10_000, int(base.get("default_limit", 50))))
    except (TypeError, ValueError):
        base["default_limit"] = 50
    return base


def normalize_user_preferences(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Mergea con defaults; strictness y default_limit parten del env si no hay archivo."""
    from config.settings import get_settings

    s = get_settings()
    base = dict(DEFAULT_USER_PREFERENCES)
    base["sql_safety_strictness"] = s.safety.sql_safety_strictness
    base["default_limit"] = s.safety.default_limit
    if not raw:
        return _coerce_pref_dict(base)
    base.update(raw)
    if raw.get("language") and "preferred_language" not in raw:
        base["preferred_language"] = raw["language"]
    if raw.get("output_format") and "preferred_output_format" not in raw:
        base["preferred_output_format"] = raw["output_format"]
    base["preferred_language"] = normalize_language_code(str(base.get("preferred_language", "es")))
    return _coerce_pref_dict(base)


def merge_and_save_user_preferences(data_dir: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Fusiona `patch` con el JSON persistido y lo guarda (p. ej. idioma tras pedido del usuario)."""
    store = PersistentStore(f"{data_dir}/user_preferences.json")
    merged = normalize_user_preferences({**(store.load() or {}), **patch})
    store.save(merged)
    return merged


def prefs_for_prompts(prefs: dict[str, Any]) -> dict[str, Any]:
    """Claves cómodas para prompts (idioma, formato, fecha, límites)."""
    p = normalize_user_preferences(prefs)
    return {
        "language": p["preferred_language"],
        "output_format": p["preferred_output_format"],
        "date_format": p["preferred_date_format"],
        "sql_safety_strictness": p["sql_safety_strictness"],
        "default_limit": p["default_limit"],
    }


def normalize_language_code(raw: str | None) -> str:
    """Normaliza a \"es\" o \"en\" para prompts y plantillas de UI."""
    s = (raw or "es").strip().lower()
    if s in ("en", "english", "inglés", "ingles"):
        return "en"
    return "es"


# Mensajes muy cortos o cambio explícito de idioma
_STANDALONE_EN = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hoi",
        "thanks",
        "thank you",
        "thx",
        "english",
        "en",
        "in english",
        "please",
        "capabilities",
        "capability",
        "help",
    }
)
_STANDALONE_ES = frozenset(
    {
        "hola",
        "buenas",
        "gracias",
        "chau",
        "adiós",
        "adios",
        "español",
        "spanish",
        "es",
        "en español",
        "en espanol",
    }
)

_EN_LEX = frozenset(
    {
        "the",
        "is",
        "are",
        "was",
        "what",
        "how",
        "many",
        "much",
        "top",
        "need",
        "want",
        "you",
        "your",
        "answer",
        "respond",
        "reply",
        "speak",
        "write",
        "tell",
        "using",
        "use",
        "could",
        "would",
        "should",
        "can",
        "will",
        "just",
        "about",
        "into",
        "hi",
        "hey",
        "hello",
        "in",
        "to",
        "for",
        "movie",
        "movies",
        "film",
        "films",
        "rental",
        "rentals",
        "customer",
        "customers",
        "actor",
        "actors",
        "show",
        "list",
        "give",
        "me",
        "with",
        "from",
        "where",
        "when",
        "which",
        "who",
        "all",
        "most",
        "viewed",
        "popular",
        "payment",
        "payments",
        "please",
        "english",
        "capabilities",
        "capability",
        "help",
    }
)
_ES_LEX = frozenset(
    {
        "las",
        "los",
        "del",
        "una",
        "unos",
        "qué",
        "que",
        "cómo",
        "como",
        "cuántas",
        "cuántos",
        "cuantos",
        "dame",
        "deme",
        "pelis",
        "películas",
        "peliculas",
        "más",
        "mas",
        "vistas",
        "visto",
        "tablas",
        "clientes",
        "alquileres",
        "actores",
        "pagos",
        "gracias",
        "español",
        "espanol",
    }
)


def effective_response_language(
    prefs: dict[str, Any] | None,
    last_user_text: str,
) -> str:
    """Idioma para respuestas de UI y prompts: preferencia + heurística del último mensaje."""
    base = normalize_language_code(prefs_for_prompts(prefs or {})["language"])
    t = (last_user_text or "").strip().lower()
    t_norm = re.sub(r"\s+", " ", t)
    if t_norm in _STANDALONE_EN or t_norm.startswith("english"):
        return "en"
    if t_norm in _STANDALONE_ES:
        return "es"
    words = set(re.findall(r"[a-záéíóúñü]+", t))
    en_hits = len(words & _EN_LEX)
    es_hits = len(words & _ES_LEX)
    if en_hits >= 2 and en_hits > es_hits:
        return "en"
    if es_hits >= 2 and es_hits > en_hits:
        return "es"
    if en_hits >= 1 and es_hits == 0 and len(words) >= 2:
        return "en"
    return base
