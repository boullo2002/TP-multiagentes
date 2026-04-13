# TODO de cierre de consigna (auditoría contra enunciado)

Este documento resume qué pide la consigna, qué está cubierto hoy en el repo y qué falta para una entrega 100% alineada.

---

## 1) Estado general (rápido)

### ✅ Ya cubierto (alto nivel)

- Implementación con **LangGraph** y grafo explícito de nodos/edges/routing.
- Arquitectura de **dos agentes especializados**:
  - `SchemaAgent`
  - `QueryAgent`
- **HITL** en flujo de schema y en consultas riesgosas.
- Memoria:
  - persistente (`user_preferences.json`, `schema_descriptions.json`)
  - corto plazo (`short_term` + `SessionStore`)
- MCP:
  - tool de inspección de schema
  - tool de ejecución SQL read-only
  - logging/trace en cliente y servidor MCP
- Guardrails de seguridad SQL (solo lectura, single statement, bloqueo DDL/DML).
- Tests unitarios/funcionales e integración opcional MCP.

### ⚠️ Parcial / a reforzar

- Planner actual es **mínimo** (regla simple), cumple estructura pero no “calidad de planificación” fuerte.
- Observabilidad de **retry/fallback behavior**: hay manejo de errores, pero no un mecanismo explícito de retries con política clara.

### ❌ Faltantes de entregable (críticos para evaluación)

- **Diagrama de arquitectura del grafo** en `README.md` (la consigna lo pide explícitamente).
- **Demo script formal** con los escenarios requeridos (schema session + 3 queries + 1 follow-up).
- **Informe corto (1-2 páginas)** de decisiones y trade-offs.

---

## 2) Checklist de aceptación de la consigna

## Checklist técnico mínimo

- [x] Built with LangGraph.
- [x] Exactly two specialized agents are implemented and used.
- [x] Human-in-the-loop in schema documentation flow.
- [x] Persistent memory stores user preferences across sessions.
- [x] Short-term memory supports conversational continuity.
- [x] MCP tools implemented and called from graph nodes.
- [x] NL → SQL with safe execution path.
- [x] Result includes SQL + sample + explanation.
- [x] Testing stack con `pytest` + `ruff`.
- [ ] README con **diagrama de arquitectura** explícito.
- [ ] Demo scenarios documentados como **script reproducible**.
- [ ] Reporte 1-2 páginas con trade-offs.

## Dataset obligatorio (DVD Rental)

- [x] Restore automatizado (`docker/db/init/01_restore_dvdrental.sh`).
- [x] Compose con DB+MCP+app+UI.
- [ ] README debería dejar **más explícito** el prerequisito de `db-data/dvdrental.zip` y validación de carga (paso a paso de demo).

---

## 3) Qué falta y cómo hacerlo (plan de cierre)

## P0 — Entregables obligatorios faltantes

### 1) Agregar diagrama de arquitectura en `README.md`

**Objetivo:** cumplir requisito explícito del enunciado.

**Cómo:**

1. Agregar sección `## Arquitectura (LangGraph + 2 agentes)`.
2. Incluir diagrama (Mermaid recomendado) con nodos:
   - router
   - schema flow (`schema_load -> schema_inspect -> schema_draft -> schema_hitl -> schema_persist`)
   - query flow (`query_load -> query_plan -> query_sql -> query_validate -> query_hitl/execute -> query_explain -> query_mem`)
3. Mostrar dónde intervienen:
   - memoria persistente
   - short-term memory
   - MCP schema/sql
   - checkpoints HITL

**Definition of done:** README contiene diagrama y breve explicación de cada bloque.

---

### 2) Crear script de demo reproducible

**Objetivo:** cumplir sección “Demo script with at least...” de la consigna.

**Cómo (propuesta):**

Crear `demo/DEMO.md` + `demo/demo.sh` con:

1. **Preflight**
   - `docker compose up --build -d`
   - check `GET /health`
   - check tablas DVD Rental (`\dt`)
2. **Escenario A — Schema documentation con corrección humana**
   - pedir documentación de schema
   - responder con edición manual o `APPROVE`
3. **Escenario B — 3 queries NL distintas**
   - ejemplo 1: agregación simple
   - ejemplo 2: join con filtro
   - ejemplo 3: top-N
4. **Escenario C — Follow-up refinement**
   - “Ahora solo para 2006”
5. Guardar capturas de request/response (o transcript) para evidencia.

**Definition of done:** cualquier corrector puede ejecutar los pasos y reproducir los resultados.

---

### 3) Crear informe corto de diseño (1-2 páginas)

**Objetivo:** cumplir entregable académico.

**Cómo:**

Crear `report.md` con estas secciones:

1. Problema y objetivos.
2. Arquitectura multiagente y por qué dos agentes.
3. Memoria (persistente vs short-term) y trade-offs.
4. MCP y seguridad SQL (defense in depth).
5. Patrones usados (router, planner/executor, validator, HITL).
6. Riesgos conocidos y mejoras futuras.

**Definition of done:** documento breve, claro, con justificación técnica.

---

## P1 — Mejoras recomendadas para subir nota

### 4) Mejorar Planner (calidad, no solo estructura)

**Situación actual:** `planner.py` cumple separación, pero el plan es muy básico.

**Mejora sugerida:**

- Enriquecer `QueryPlan` con:
  - tablas candidatas
  - columnas objetivo
  - filtros detectados
  - nivel de riesgo
  - supuestos
- Opcional: planner asistido por LLM con salida JSON validada.

---

### 5) Retry/fallback explícito y observable

**Situación actual:** hay manejo de errores, pero no política formal de retry.

**Mejora sugerida:**

- Definir retry para fallas transitorias MCP (timeout/connect).
- Backoff corto con tope.
- Logging dedicado: `retry_attempt`, `retry_reason`, `retry_exhausted`.

---

### 6) Robustecer README de setup DVD Rental

**Mejora sugerida:**

- Agregar sección “Dataset obligatorio”:
  - dónde colocar `db-data/dvdrental.zip`
  - comando para validar restore
  - troubleshooting típico

---

## 4) Orden sugerido de ejecución

1. `README.md` con diagrama (P0).
2. `demo/DEMO.md` + `demo/demo.sh` (P0).
3. `report.md` (P0).
4. Planner enriquecido (P1).
5. Retry/fallback explícito (P1).
6. Re-run quality gates:
   - `uv run ruff check src tests`
   - `uv run ruff format --check src tests`
   - `uv run pytest`

---

## 5) Riesgo de evaluación si se entrega hoy

Si se entrega exactamente como está ahora, el riesgo principal no está en el core técnico (que está bastante completo), sino en **faltantes de entregables formales**:

- diagrama en README,
- demo script explícito con escenarios exigidos,
- reporte de 1-2 páginas.

Eso puede impactar la rúbrica en **Code quality & documentation** y parte de **Architecture quality** (evidencia/comunicación).
