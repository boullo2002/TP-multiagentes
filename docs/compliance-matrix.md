# Matriz de cumplimiento `task.md`

| Requisito | Evidencia actual | Gap | Accion |
|---|---|---|---|
| LangGraph con nodos/rutas explicitas | `src/graph/query_workflow.py`, `src/graph/schema_workflow.py` | Sin gap critico | Mantener y reforzar trazabilidad |
| 2 agentes especializados | `src/agents/schema_agent.py`, `src/agents/query_agent.py` | No estaban en ReAct explicito | Implementar loop ReAct en ambos agentes |
| HITL en schema | `schema_draft_context` + resume en `src/graph/schema_workflow.py` | Sin gap critico | Mantener y documentar mejor |
| Memoria persistente + short-term | `src/memory/*`, `query_load_context` | Sin gap critico | Asegurar evidencia en README/demo |
| MCP tools integradas en grafo | `src/tools/mcp_*`, `query_execute`, `schema_inspect_metadata` | Habia restos legacy en tests/docs | Migrar todo a `tools/list` + `tools/call` |
| Tool calls trazables | Logs en `src/tools/mcp_client.py` y `mcp_server/server.py` | Falta estandarizar eval de trazas | Agregar pruebas y checklist de observabilidad |
| Planner/Executor + Validator | `src/agents/planner.py`, `query_sql_executor`, `query_validator_node` | Sin gap critico | Mantener + robustecer recovery |
| Recovery (retries/circuit breaker) | retries SQL en `query_validator_node` | Falta anti-loop explicito y contador de repeticion | Agregar deteccion de SQL repetida + corte |
| SQL safe/read-only | `src/tools/sql_safety.py`, `mcp_server/tools/sql.py` | Sin gap critico | Reforzar tests |
| README/demo rubric-ready | `README.md`, `demo/DEMO.md` | Varias referencias legacy y falta explicitar ReAct/evals | Actualizar documentacion final |

## Prioridad de ejecucion

1. MCP estandar completo (servidor, cliente, tests y docs).
2. ReAct en Query Agent y Schema Agent.
3. Recovery robusto (anti-loop + circuit breaker pragmatico).
4. Cobertura de tests y evidencia de trazabilidad.
5. Ajuste final de README/demo/specs para entrega.
