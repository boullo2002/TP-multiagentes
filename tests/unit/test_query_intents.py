from __future__ import annotations

from graph.query_workflow import _has_domain_anchor, _is_non_informative_query


def test_non_informative_query_marks_question_mark() -> None:
    assert _is_non_informative_query("?") is True


def test_domain_anchor_rejects_unknown_entities() -> None:
    state = {
        "schema_context": {
            "table_names": ["film", "actor", "rental", "customer"],
        },
        "short_term": {},
    }
    assert _has_domain_anchor(state, "dame las bananas mas ricas") is False


def test_domain_anchor_accepts_known_entities() -> None:
    state = {
        "schema_context": {
            "table_names": ["film", "actor", "rental", "customer"],
        },
        "short_term": {},
    }
    assert _has_domain_anchor(state, "dame las peliculas mas vistas") is True
