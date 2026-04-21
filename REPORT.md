# Reporte corto — TP Multiagentes

## 1) Objetivo y alcance

Este trabajo implementa un prototipo de sistema NLQ (Natural Language Query) sobre PostgreSQL (dataset DVD Rental) con LangGraph, arquitectura de dos agentes y uso de herramientas MCP.  
El objetivo principal fue resolver consultas en lenguaje natural de forma segura y explicable, separando responsabilidades entre:

- **Schema Agent**: inspección/documentación de schema con HITL.
- **Query Agent**: NL -> SQL read-only, validación y explicación de resultados.

El sistema prioriza seguridad, trazabilidad y continuidad conversacional.

---

## 2) Decisiones de arquitectura

### 2.1 Orquestación con LangGraph

Se eligió un grafo explícito para modelar estados y transiciones:

- `query_workflow`: router -> carga contexto/memoria -> planner -> SQL -> validator -> execute -> explain -> memoria.
- `schema_workflow`: router -> inspección schema -> draft -> HITL (si corresponde) -> persistencia.

**Motivación:** tener control determinístico del flujo, guardrails claros y fácil observabilidad por nodo.

### 2.2 Dos agentes especializados

- **Schema Agent** recibe metadata real del schema y produce contexto persistente para consultas futuras.
- **Query Agent** usa pregunta + contexto + memoria para redactar SQL read-only.

**Motivación:** separar “conocimiento estructural del dominio” de “ejecución de consulta”, reduciendo ambigüedad y acoplamiento.

### 2.3 MCP como capa de acceso a datos

Se implementó servidor MCP separado (`mcp_server`) y cliente MCP en backend (`src/tools/mcp_client.py`), con dos tools principales:

- `db_schema_inspect`
- `db_sql_execute_readonly`

**Motivación:** aislar acceso a DB, mejorar seguridad operacional y trazabilidad de tool calls.

---

## 3) Patrones aplicados

Se aplicaron los patrones pedidos en la consigna:

- **Planner/Executor**: planificación heurística de tablas/supuestos (`planner.py`) antes de generar SQL.
- **Critic/Validator**: validación de SQL (`validator.py` + `sql_safety.py`) antes de ejecutar.
- **HITL**: checkpoint humano en flujo de schema cuando hay ambigüedades.
- **Router/Guardrails/Retries**: detección de intents básicos, reintentos controlados y bloqueos de seguridad.

Nota: la arquitectura implementada es de orquestación por grafo, no un agente autónomo tipo ReAct tool-calling.

---

## 4) Diseño de memoria

### 4.1 Memoria persistente

- `user_preferences.json`: idioma, formato de salida, formato de fecha, strictness y límites por defecto.
- `schema_context.json`: contexto de schema aprobado (markdown + catálogo + hash + preguntas/respuestas).

**Impacto:** mejora consistencia entre sesiones y precisión de NL -> SQL.

### 4.2 Memoria de corto plazo (sesión)

`short_term` + `SessionStore`: última pregunta, SQL draft/ejecutada, tablas/filtros recientes, supuestos y preview de resultados.

**Impacto:** permite follow-up natural (refinamientos sucesivos sin perder contexto).

---

## 5) Seguridad y robustez

### 5.1 Seguridad SQL

Controles en dos capas:

1. **Backend app**: validación sintáctica/política (solo lectura, single statement, restricciones).
2. **MCP server**: revalidación antes de tocar la base (defense in depth).

### 5.2 Manejo de errores

- Errores MCP (infra/transporte) diferenciados de errores funcionales.
- Mensajes de fallback amigables para UI.
- Circuito de reintentos con corte cuando se detecta repetición de SQL (evita loops).

### 5.3 Observabilidad

Se registran:

- transiciones de nodos del grafo,
- invocaciones de tools MCP (tool, request id, elapsed, resultado/error),
- eventos de retry/bloqueo/HITL.

---

## 6) Trade-offs principales

1. **Control determinístico vs autonomía del agente**
   - A favor: mayor previsibilidad y auditabilidad.
   - En contra: menos flexibilidad exploratoria del LLM.

2. **Simplicidad heurística del planner**
   - A favor: rápido, barato y estable.
   - En contra: cobertura semántica limitada frente a consultas ambiguas/no estándar.

3. **HITL focalizado en schema**
   - A favor: reduce costo operativo durante querying.
   - En contra: si el criterio docente exige HITL explícito en query riesgosa, podría pedirse una extensión.

4. **Persistencia en JSON local**
   - A favor: simple y suficiente para prototipo/evaluación.
   - En contra: no ideal para escala multi-instancia.

---

## 7) Estado frente a la consigna

El sistema cumple los ejes centrales:

- LangGraph con nodos/edges/routing.
- Dos agentes especializados.
- MCP tools integradas en workflow.
- Memoria persistente y short-term.
- SQL read-only con validación.
- Respuesta con SQL + preview + explicación.
- Flujo de schema con HITL y persistencia.

Quedan como tareas de cierre de entrega:

- validar evidencia final end-to-end en DVD Rental (demo),
- ejecutar suite final de tests/lint y adjuntar resultado,
- consolidar commit limpio final.

---

## 8) Mejoras futuras

- HITL opcional también en query de alto riesgo (según política).
- Validación semántica más rica contra schema (no solo tablas; también columnas/tipos).
- Configuración por feature flags para comportamientos de frontend (ej. suppress de auto-followups).
- Migrar memoria persistente a backend transaccional si se requiere escala.

---

## 9) Teoría -> evidencia en código

- **LangGraph / state machine:** `src/graph/query_workflow.py` y `src/graph/schema_workflow.py` modelan la orquestación con estado compartido, routing y ciclos de retry.
- **Separación de agentes:** `SchemaAgent` (`src/agents/schema_agent.py`) y `QueryAgent` (`src/agents/query_agent.py`) implementan responsabilidades diferenciadas.
- **Planner/Executor:** `src/agents/planner.py` planifica tablas/supuestos y `QueryAgent` ejecuta la generación SQL.
- **Critic/Validator:** `src/agents/validator.py` + `src/tools/sql_safety.py` aplican chequeos previos y bloqueos.
- **HITL:** `src/graph/schema_workflow.py` implementa checkpoints humanos (`APPROVE` o `answers` JSON) antes de persistir.
- **Memoria persistente + short-term:** stores en `src/memory/*` y actualización de contexto de sesión en `query_mem`.
- **Artefacto semántico tabla/columna:** se genera en `SchemaAgent.draft_descriptions`, se normaliza y persiste como `semantic_descriptions` en `schema_context`.
- **MCP/tool abstraction:** servidor MCP en `mcp_server/tools/` y cliente HTTP desacoplado en `src/tools/mcp_client.py`.
- **Observabilidad de trayectoria:** el estado incluye `trajectory` (latencia por nodo, retries, bloqueos de seguridad, token usage y eventos), logueado al cerrar cada flujo.

