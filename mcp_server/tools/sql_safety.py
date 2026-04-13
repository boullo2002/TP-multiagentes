from __future__ import annotations

import re

_UNSAFE = re.compile(
    r"\b(insert|update|delete|alter|drop|truncate|create|grant|revoke)\b", re.IGNORECASE
)


def _only_trailing_comments_after_semicolon(fragment: str) -> bool:
    """True si tras el último ';' solo hay espacio y/o comentarios `--` / `/* */`."""
    s = fragment.strip()
    if not s:
        return True
    while "/*" in s:
        i = s.find("/*")
        j = s.find("*/", i + 2)
        if j == -1:
            return False
        s = (s[:i] + s[j + 2 :]).strip()
    if not s:
        return True
    for line in s.splitlines():
        t = line.strip()
        if t and not t.startswith("--"):
            return False
    return True


def _after_leading_comments(sql: str) -> str:
    """Quita comentarios `--` y `/* */` al inicio para detectar SELECT/WITH."""
    s = sql.strip()
    while s:
        if s.startswith("--"):
            nl = s.find("\n")
            s = "" if nl == -1 else s[nl + 1 :].lstrip()
        elif s.startswith("/*"):
            end = s.find("*/")
            if end == -1:
                break
            s = s[end + 2 :].lstrip()
        else:
            break
    return s.lstrip("(").strip()


def _is_single_statement(sql: str) -> bool:
    stripped = sql.strip()
    if ";" not in stripped:
        return True
    last_semi = stripped.rfind(";")
    after = stripped[last_semi + 1 :]
    if not _only_trailing_comments_after_semicolon(after):
        return False
    core = stripped[: last_semi + 1]
    return core.count(";") == 1


def _is_readonly_select(sql: str) -> bool:
    s = _after_leading_comments(sql)
    return s[:6].lower() == "select" or s[:4].lower() == "with"


def enforce_readonly(sql: str) -> None:
    """Defensa en profundidad (spec-mcp §3.4); debe alinearse con src/tools/sql_safety."""
    if not sql.strip():
        raise ValueError("SQL vacío.")
    if _UNSAFE.search(sql):
        raise ValueError("SQL contiene keywords no permitidas (DDL/DML).")
    if not _is_single_statement(sql):
        raise ValueError("SQL contiene múltiples statements; no se permite.")
    if not _is_readonly_select(sql):
        raise ValueError("Solo se permite SQL de lectura (SELECT).")
