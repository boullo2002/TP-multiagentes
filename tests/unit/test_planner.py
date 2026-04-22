from __future__ import annotations

from agents.planner import build_plan, maybe_refine_plan_with_llm


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


def test_matches_spanish_question_to_english_table_via_semantics() -> None:
    plan = build_plan(
        "mostrame las peliculas mas alquiladas",
        schema_catalog={
            "tables": [
                {
                    "name": "film",
                    "columns": [{"name": "film_id"}, {"name": "title"}],
                },
                {
                    "name": "rental",
                    "columns": [{"name": "rental_id"}, {"name": "inventory_id"}],
                },
            ]
        },
        semantic_schema_descriptions={
            "film": {
                "description": "Tabla de peliculas disponibles para alquiler",
                "columns": {"title": "Titulo de la pelicula"},
            }
        },
        short_term={},
        language="es",
    )

    assert "film" in plan.tables
    assert plan.confidence >= 0.4


def test_plural_and_english_mapping_for_customers() -> None:
    plan = build_plan(
        "show top 5 customers by total payments",
        schema_catalog={
            "tables": [
                {
                    "name": "customer",
                    "columns": [{"name": "customer_id"}, {"name": "first_name"}],
                },
                {
                    "name": "payment",
                    "columns": [{"name": "customer_id"}, {"name": "amount"}],
                },
            ]
        },
        short_term={},
        language="en",
    )

    assert "customer" in plan.tables
    assert "payment" in plan.tables


def test_fallback_llm_refines_low_confidence_plan(monkeypatch) -> None:
    base = build_plan(
        "quiero datos de compradores frecuentes",
        schema_catalog={
            "tables": [
                {"name": "customer", "columns": [{"name": "customer_id"}]},
                {"name": "payment", "columns": [{"name": "payment_id"}, {"name": "customer_id"}]},
            ]
        },
        short_term={},
        language="es",
    )

    class _Msg:
        content = """{
          "summary": "Refined by fallback",
          "tables": ["customer", "payment", "invented_table"],
          "assumptions": ["Frecuencia via cantidad de pagos por cliente."],
          "confidence": 0.78,
          "needs_clarification": false,
          "clarification_question": ""
        }"""

    class _LLM:
        def invoke(self, *_args, **_kwargs):
            return _Msg()

    class _Client:
        def get(self):
            return _LLM()

    monkeypatch.setattr("agents.planner.LLMClient", _Client)
    refined = maybe_refine_plan_with_llm(
        plan=base,
        user_question="quiero datos de compradores frecuentes",
        schema_catalog={
            "tables": [
                {"name": "customer", "columns": [{"name": "customer_id"}]},
                {"name": "payment", "columns": [{"name": "payment_id"}, {"name": "customer_id"}]},
            ]
        },
        semantic_schema_descriptions={},
        language="es",
        enabled=True,
        confidence_threshold=0.95,
    )
    assert refined.summary == "Refined by fallback"
    assert refined.confidence == 0.78
    assert refined.tables == ["customer", "payment"]


def test_fallback_llm_keeps_base_plan_on_error(monkeypatch) -> None:
    base = build_plan(
        "consulta ambigua",
        schema_catalog={"tables": [{"name": "film", "columns": [{"name": "film_id"}]}]},
        short_term={},
        language="es",
    )

    class _ClientFail:
        def get(self):
            raise RuntimeError("boom")

    monkeypatch.setattr("agents.planner.LLMClient", _ClientFail)
    refined = maybe_refine_plan_with_llm(
        plan=base,
        user_question="consulta ambigua",
        schema_catalog={"tables": [{"name": "film", "columns": [{"name": "film_id"}]}]},
        semantic_schema_descriptions={},
        language="es",
        enabled=True,
        confidence_threshold=1.0,
    )
    assert refined == base
