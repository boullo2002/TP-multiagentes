from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from langsmith import traceable

from agents.schema_agent import SchemaAgent
from config.settings import get_settings
from memory.persistent_store import PersistentStore
from memory.schema_context_store import SchemaContextStore
from memory.user_preferences import normalize_user_preferences
from tools.mcp_schema_tool import schema_inspect


def _build_schema_catalog(schema_metadata: dict[str, Any]) -> dict[str, Any]:
    catalog_tables: list[dict[str, Any]] = []
    for t in schema_metadata.get("tables") or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        cols_out: list[dict[str, Any]] = []
        for c in t.get("columns") or []:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            cols_out.append(
                {
                    "name": c.get("name"),
                    "type": c.get("type"),
                    "nullable": bool(c.get("nullable", True)),
                }
            )
        catalog_tables.append(
            {
                "name": t.get("name"),
                "columns": cols_out,
                "primary_key": t.get("primary_key") or [],
                "foreign_keys": t.get("foreign_keys") or [],
                "unique_constraints": t.get("unique_constraints") or [],
            }
        )
    return {"tables": catalog_tables}


def compute_schema_hash(schema_metadata: dict[str, Any]) -> str:
    canonical = json.dumps(
        schema_metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SchemaContextRunResult:
    status: str  # ready | needs_human
    schema_hash: str
    context: dict[str, Any]
    draft: dict[str, Any] | None = None


def _stores() -> tuple[SchemaContextStore, dict[str, Any]]:
    settings = get_settings()
    ctx_store = SchemaContextStore(
        PersistentStore(f"{settings.storage.data_dir}/schema_context.json")
    )
    prefs_store = PersistentStore(f"{settings.storage.data_dir}/user_preferences.json")
    prefs = normalize_user_preferences(prefs_store.load() or {})
    return ctx_store, prefs


def run_schema_context_generation(
    *,
    force: bool = False,
    schema_metadata: dict[str, Any] | None = None,
    answers: dict[str, Any] | None = None,
    trace: bool = True,
) -> SchemaContextRunResult:
    if not trace:
        return _run_schema_context_generation_core(
            force=force,
            schema_metadata=schema_metadata,
            answers=answers,
        )

    holder: dict[str, Any] = {}
    _run_schema_context_generation_traced(
        force=force,
        schema_metadata=schema_metadata,
        answers=answers,
        _holder=holder,
    )
    result = holder.get("result")
    if isinstance(result, SchemaContextRunResult):
        return result
    return _run_schema_context_generation_core(
        force=force,
        schema_metadata=schema_metadata,
        answers=answers,
    )


@traceable(
    name="schema_context_generation",
    run_type="chain",
    tags=["workflow:schema", "service:schema_context"],
)
def _run_schema_context_generation_traced(
    *,
    force: bool = False,
    schema_metadata: dict[str, Any] | None = None,
    answers: dict[str, Any] | None = None,
    _holder: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _run_schema_context_generation_core(
        force=force,
        schema_metadata=schema_metadata,
        answers=answers,
    )
    if _holder is not None:
        _holder["result"] = result
    draft = result.draft if isinstance(result.draft, dict) else {}
    questions = draft.get("questions") if isinstance(draft, dict) else []
    return {
        "status": result.status,
        "schema_hash": result.schema_hash,
        "has_context": bool(result.context),
        "context_keys": sorted(result.context.keys()) if isinstance(result.context, dict) else [],
        "has_draft": result.draft is not None,
        "draft_question_count": len(questions) if isinstance(questions, list) else 0,
    }


def _run_schema_context_generation_core(
    *,
    force: bool = False,
    schema_metadata: dict[str, Any] | None = None,
    answers: dict[str, Any] | None = None,
) -> SchemaContextRunResult:
    ctx_store, prefs = _stores()
    metadata = (
        schema_metadata
        if schema_metadata is not None
        else schema_inspect(schema=None, include_views=False)
    )
    current_hash = compute_schema_hash(metadata)
    existing = ctx_store.load() or {}
    existing_md = str(existing.get("context_markdown") or "")
    existing_hash = str(existing.get("schema_hash") or "")
    existing_answers = existing.get("answers") if isinstance(existing.get("answers"), dict) else {}
    merged_answers = dict(existing_answers or {})
    if answers:
        merged_answers.update(answers)

    if (
        not force
        and existing_md.strip()
        and existing_hash
        and existing_hash == current_hash
    ):
        return SchemaContextRunResult(
            status="ready",
            schema_hash=current_hash,
            context=existing,
            draft=None,
        )

    draft = SchemaAgent().draft_context(
        metadata,
        existing_context_markdown=existing_md,
        human_answers=merged_answers,
        user_preferences=prefs,
    )
    questions = draft.get("questions") if isinstance(draft, dict) else None
    has_questions = bool(questions) and isinstance(questions, list) and len(questions) > 0
    if has_questions:
        return SchemaContextRunResult(
            status="needs_human",
            schema_hash=current_hash,
            context=existing,
            draft=draft,
        )

    ctx_md = str(draft.get("context_markdown") or "")
    table_names: list[str] = []
    for t in metadata.get("tables") or []:
        if isinstance(t, dict) and t.get("name"):
            table_names.append(str(t["name"]))
    table_names = sorted(set(table_names))
    schema_catalog = _build_schema_catalog(metadata)
    ctx_store.save(
        context_markdown=ctx_md,
        schema_hash=current_hash,
        table_names=table_names,
        schema_catalog=schema_catalog,
        questions=[],
        answers=merged_answers,
    )
    return SchemaContextRunResult(
        status="ready",
        schema_hash=current_hash,
        context=ctx_store.load(),
        draft=draft,
    )

