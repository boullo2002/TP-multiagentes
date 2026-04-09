from __future__ import annotations

from dataclasses import asdict, dataclass

from config.settings import get_settings
from tools.sql_safety import SafetyResult, validate_sql


@dataclass(frozen=True)
class ValidationOutput:
    is_safe: bool
    needs_human_approval: bool
    issues: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def validate_sql_draft(sql: str) -> ValidationOutput:
    settings = get_settings()
    res: SafetyResult = validate_sql(sql, strictness=settings.safety.sql_safety_strictness)
    issues: list[str] = []
    if not res.ok:
        issues.append(res.reason or "SQL inválido.")
    if res.needs_human_approval:
        issues.append(res.reason or "Requiere aprobación humana.")
    return ValidationOutput(
        is_safe=res.ok,
        needs_human_approval=res.needs_human_approval,
        issues=issues,
    )
