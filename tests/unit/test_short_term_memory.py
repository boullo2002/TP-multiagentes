from __future__ import annotations

from memory.short_term import build_short_term_update


def test_short_term_stores_question_and_sql() -> None:
    st = build_short_term_update(
        prior_short_term={},
        last_user_question="Top películas 2006",
        sql_draft="SELECT 1",
        sql_validated="SELECT * FROM film WHERE release_year = 2006 LIMIT 10",
        query_plan={"tables": ["film"], "assumptions": ["año en release_year"]},
        query_result={"columns": ["title"], "rows": [["X"]], "row_count": 1},
    )
    assert st["last_user_question"] == "Top películas 2006"
    assert "film" in st["recent_tables"]
    assert any("2006" in x for x in st["recent_filters"])
    assert st["last_result_preview"]["row_count"] == 1
