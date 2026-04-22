from __future__ import annotations

from agents.planner import build_plan


def test_no_clarification_when_schema_exists_without_lexical_match() -> None:
    plan = build_plan(
        "dame las peliculas mas vistas",
        schema_catalog={
            "tables": [
                {"name": "film", "columns": [{"name": "film_id"}, {"name": "title"}]},
                {"name": "rental", "columns": [{"name": "rental_id"}, {"name": "inventory_id"}]},
            ]
        },
        short_term={},
        language="es",
    )

    assert plan.needs_clarification is False
