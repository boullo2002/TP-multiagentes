from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryPlan:
    summary: str
    tables: list[str]
    assumptions: list[str]


def build_plan(user_question: str) -> QueryPlan:
    # Minimal explicit planner. The LLM-based planner can replace this later.
    return QueryPlan(
        summary=f"Interpretar pregunta y mapear a tablas relevantes: {user_question}",
        tables=[],
        assumptions=[],
    )
