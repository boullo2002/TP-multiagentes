# TODO de cierre contra `task.md`

Auditoría rápida al 2026-04-17 sobre el estado real del repo.

## Cumplimiento actual

- [x] LangGraph con estado, nodos, aristas y ruteo explícito.
- [x] Dos agentes especializados separados (`SchemaAgent` y `QueryAgent`).
- [x] HITL en flujo de documentación de schema.
- [x] Memoria persistente y short-term documentadas e implementadas.
- [x] MCP tools implementadas y usadas en ejecución de grafos.
- [x] SQL read-only con validación/guardrails.
- [x] Resultado de query con SQL + muestra + explicación.
- [x] Dataset DVD Rental integrado en Docker (restore + verificación).
- [x] Tests unitarios/funcionales con `pytest` y calidad con `ruff`.

## Pendientes reales para quedar 100% alineado a entregables

- [ ] Agregar **diagrama de arquitectura** en `README.md` (requisito explícito).
- [ ] Agregar **demo script reproducible** (README o archivo aparte) con:
  - [ ] 1 sesión de schema con corrección humana,
  - [ ] 3 consultas NL diferentes,
  - [ ] 1 follow-up refinement,
  - [ ] evidencia de ejecución sobre DVD Rental.
- [ ] Crear **`REPORT.md`** (1–2 páginas) con decisiones y trade-offs.

## Nota de alineación (importante)

- [ ] El enunciado original menciona HITL antes de ejecutar queries riesgosas.  
      Implementación actual: sin HITL SQL para el usuario final del Query Agent
      (auto-fix + reintentos + bloqueo con reformulación en lenguaje natural).
      Confirmar si esta desviación está aceptada por el docente.

## Prioridad sugerida

1. `REPORT.md`
2. Diagrama + demo script en `README.md` (o `demo/DEMO.md`)
3. Validación final de criterio docente sobre HITL en Query Agent
