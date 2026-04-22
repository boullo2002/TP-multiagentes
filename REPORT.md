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

### 2.1.1 Routing híbrido de intención (determinístico + fallback LLM)

Se incorporó una segunda capa de clasificación para el ingreso de consultas:

- Capa 1: reglas determinísticas en `basic_intents`.
- Capa 2: fallback LLM para casos ambiguos (`INTENT_FALLBACK_ENABLED`), con salida JSON estricta y umbral de confianza.

Escenarios explícitos de input:

1. `capabilities`
2. `schema_inventory`
3. `data_query`
4. `off_topic`

Solo `data_query` continúa a planner/SQL. Ante duda o error en fallback, la política es **safe default** (bloquear y pedir reformulación).

### 2.2 Dos agentes especializados

- **Schema Agent** recibe metadata real del schema y produce contexto persistente para consultas futuras.
- **Query Agent** usa pregunta + contexto + memoria para redactar SQL read-only.

**Motivación:** separar “conocimiento estructural del dominio” de “ejecución de consulta”, reduciendo ambigüedad y acoplamiento.

### 2.2.1 Planner híbrido y decisión operativa

El planner quedó preparado en dos niveles:

- nivel heurístico determinístico (rápido y barato),
- fallback LLM opcional (`PLANNER_FALLBACK_ENABLED`) para baja confianza.

Decisión para demo y operación estable: priorizar fallback LLM en **intent routing** y dejar el fallback del planner configurable (incluso desactivado) para reducir latencia/costo cuando no es necesario.

### 2.3 MCP como capa de acceso a datos

Se implementó servidor MCP separado (`mcp_server`) y cliente MCP en backend (`src/tools/mcp_client.py`), con dos tools principales:

- `db_schema_inspect`
- `db_sql_execute_readonly`

**Motivación:** aislar acceso a DB, mejorar seguridad operacional y trazabilidad de tool calls.

---

## 3) Patrones aplicados

Se aplicaron los patrones pedidos en la consigna:

- **Planner/Executor**: planificación heurística de tablas/supuestos (`planner.py`) antes de generar SQL, con fallback LLM opcional para refinamiento.
- **Critic/Validator**: validación de SQL (`validator.py` + `sql_safety.py`) antes de ejecutar.
- **HITL**: checkpoint humano en flujo de schema cuando hay ambigüedades.
- **Router/Guardrails/Retries**: detección de intents básicos, fallback LLM para ambiguos, reintentos controlados y bloqueos de seguridad.

Nota: la arquitectura implementada es de orquestación por grafo, no un agente autónomo tipo ReAct tool-calling. En query riesgosa se aplica validación + bloqueo/retry; no hay HITL explícito en ese flujo.

---

## 3.1 Flujo nodo por nodo (qué hace cada uno y cómo)

### Query Workflow (`src/graph/query_workflow.py`)

1. **`mark_query_mode`**  
   Fija `mode="query"` para enrutar el subgrafo correcto.

2. **`load_context`**  
   Hidrata estado desde persistencia:
   - `user_preferences` (`language`, `output_format`, `strictness`, límites),
   - `schema_context` aprobado (`context_markdown`, `schema_catalog`, `semantic_descriptions`),
   - `short_term` de sesión (`SessionStore`).
   Si falta contexto de schema, intenta regeneración automática; si requiere intervención humana, bloquea y deriva a `/schema-agent/ui`.

3. **`basic_intents` (router de seguridad)**  
   Clasifica el input en: `capabilities`, `schema_inventory`, `data_query`, `off_topic`.
   - **Heurística determinística**: regex/listas para social, capacidades, inventario de tablas, señales de data query y anclas de dominio.
   - **Fallback LLM de intención**: solo en ambiguos, salida JSON estricta (`intent_type`, `confidence`, `message`) y umbral (`INTENT_FALLBACK_CONFIDENCE_THRESHOLD`).
   - **Safe default**: ante error del LLM o baja confianza, bloquea.
   - **Follow-up refinements**: patrones como "ahora solo...", "solamente el primero sin preview", "only the first" pasan como `data_query` aunque tengan baja señal semántica.

4. **`planner`**  
   Construye `query_plan` con:
   - `tables`,
   - `assumptions`,
   - `steps`,
   - `confidence`,
   - `needs_clarification`.
   **Implementación heurística**:
   - tokenización normalizada (sin acentos),
   - expansión simple singular/plural,
   - sinónimos útiles ES/EN,
   - scoring por match en nombre de tabla/columna + columnas + `recent_tables` + descripciones semánticas.
   **Fallback opcional**:
   - `PLANNER_FALLBACK_ENABLED`,
   - se dispara por umbral de confianza,
   - guardrail: filtra tablas para aceptar solo tablas reales del catálogo.

5. **`draft_sql_llm`**  
   `QueryAgent` genera SQL read-only con contexto completo (plan, schema aprobado, semántica, short-term y feedback de retry).
   - salida esperada: una sola sentencia SQL o `CLARIFY:`.
   - manejo defensivo: si falla la llamada LLM, retorna mensaje controlado y marca bloqueo, evitando un error genérico global.

6. **`validate_sql`**  
   `validator.py` + `sql_safety.py` aplican guardrails:
   - solo `SELECT` / `WITH ... SELECT`,
   - sin DDL/DML (`DROP/DELETE/UPDATE/ALTER/...`),
   - statement único,
   - límites/normalización segura.
   Si no pasa:
   - retry con feedback hasta `QUERY_SQL_RETRY_MAX`,
   - corte de loops cuando se repite la misma SQL.

7. **`execute_sql`**  
   Ejecuta por MCP (`db_sql_execute_readonly`) con timeout y `result_max_rows` ajustado por preferencias (`default_limit` o full result con tope de seguridad).

8. **`format_answer`**  
   Arma la respuesta final con:
   - SQL ejecutado,
   - metadatos de resultado (columnas, filas, ms),
   - preview tabular markdown,
   - supuestos del planner,
   - limitaciones.

9. **`persist_session`**  
   Persiste short-term y trayectoria (`events`, retries, bloqueos, latencias, uso de tokens) para continuidad y observabilidad.

### Schema Workflow (`src/graph/schema_workflow.py`)

1. **`router schema`**  
   Distingue ejecución normal vs reanudación desde checkpoint HITL.

2. **`load estado` / `hitl resume loader`**  
   Recupera borrador, respuestas previas y estado de preguntas.

3. **`inspect schema MCP`**  
   Lee metadata real de DB (`tables`, `columns`, PK/FK y constraints disponibles).

4. **`SchemaAgent.draft_bundle`**  
   Genera:
   - contexto en lenguaje natural para querying,
   - `semantic_descriptions` por tabla/columna.  
   Si detecta ambigüedad, activa `schema_hitl_pending`.

5. **`persistir`**  
   Guarda artefacto aprobado en `schema_context.json`, reutilizado luego por planner y QueryAgent.

---

## 3.2 Decisiones de implementación importantes

- **Estado tipado (`GraphState`)**: evita acoplamiento implícito entre nodos y hace explícitos campos críticos (`query_plan`, `sql_validation`, `short_term`, `trajectory`).
- **Separación MCP cliente/servidor**: aísla acceso a DB y permite aplicar seguridad en dos capas (app + mcp).
- **Configuración por flags**: comportamiento de fallback controlado por entorno (`INTENT_FALLBACK_*`, `PLANNER_FALLBACK_*`) para ajustar costo/latencia sin cambiar código.
- **Degradación segura**: si falla LLM/fallback, el sistema prioriza bloqueo con mensaje guiado sobre ejecución insegura.
- **Compatibilidad OpenAI API**: `POST /v1/chat/completions` conserva integración con Open WebUI y script de demo reproducible.

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
- Manejo defensivo de fallos en `draft_sql` para evitar error genérico global en demo.
- Defaults seguros en routing: cuando hay incertidumbre en clasificación, no ejecuta SQL.

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

2b. **Fallback LLM en intent routing**

- A favor: mejora robustez multilenguaje y reduce falsos bloqueos del filtro determinístico.
- En contra: agrega costo/latencia y requiere umbral de confianza bien calibrado.

2c. **Fallback LLM en planner (opcional)**

- A favor: mejora recall de tablas/supuestos cuando la heurística tiene señal débil.
- En contra: puede ser redundante si el problema principal ya se resolvió en routing; mayor costo por request.

2d. **Heurísticas explícitas (routing/planner)**

- A favor: comportamiento auditable y reproducible (fácil de depurar en demo/evaluación).
- En contra: mantenimiento manual de reglas/patrones y cobertura incompleta frente a lenguaje muy libre.

3. **HITL focalizado en schema**
   - A favor: reduce costo operativo durante querying.
   - En contra: si la evaluación exige HITL también en query riesgosa, requiere extensión.

4. **Persistencia en JSON local**
   - A favor: simple y suficiente para prototipo/evaluación.
   - En contra: no ideal para escala multi-instancia.

---

## 7) Mejoras futuras

- HITL opcional también en query de alto riesgo (según política).
- Validación semántica más rica contra schema (no solo tablas; también columnas/tipos).
- Configuración por feature flags para comportamientos de frontend (ej. suppress de auto-followups).
- Migrar memoria persistente a backend transaccional si se requiere escala.

---

## 8) Teoría -> evidencia en código

- **LangGraph / state machine:** `src/graph/query_workflow.py` y `src/graph/schema_workflow.py` modelan la orquestación con estado compartido, routing y ciclos de retry.
- **Routing híbrido por escenarios:** `query_basic_intents` clasifica en `capabilities`, `schema_inventory`, `data_query`, `off_topic`; en ambiguos usa fallback LLM con umbral configurable.
- **Separación de agentes:** `SchemaAgent` (`src/agents/schema_agent.py`) y `QueryAgent` (`src/agents/query_agent.py`) implementan responsabilidades diferenciadas.
- **Planner/Executor:** `src/agents/planner.py` planifica tablas/supuestos (heurístico + fallback opcional con guardrails) y `QueryAgent` ejecuta la generación SQL.
- **Critic/Validator:** `src/agents/validator.py` + `src/tools/sql_safety.py` aplican chequeos previos y bloqueos.
- **HITL:** `src/graph/schema_workflow.py` implementa checkpoints humanos (`APPROVE` o `answers` JSON) antes de persistir.
- **Memoria persistente + short-term:** stores en `src/memory/*` y actualización de contexto de sesión en `query_mem`.
- **Artefacto semántico tabla/columna:** se genera en `SchemaAgent.draft_descriptions`, se normaliza y persiste como `semantic_descriptions` en `schema_context`.
- **MCP/tool abstraction:** servidor MCP en `mcp_server/tools/` y cliente HTTP desacoplado en `src/tools/mcp_client.py`.
- **Observabilidad de trayectoria:** el estado incluye `trajectory` (latencia por nodo, retries, bloqueos de seguridad, token usage y eventos), logueado al cerrar cada flujo.

