# Pendientes detectados vs `task.md`

## Implementado recientemente

- [x] **Persistir descripciones NL por tabla y por columna (aprobadas por humano).**  
  Se agregó `semantic_descriptions` al artefacto persistente de `schema_context`, con estructura por tabla/columna.

- [x] **Integrar en el flujo activo el artefacto de descripciones detalladas.**  
  `SchemaAgent.draft_descriptions()` quedó integrado en `schema_workflow` y el `QueryAgent` ahora consume `semantic_descriptions` al generar SQL.

- [x] **Elevar observabilidad de trayectoria.**  
  Se incorporó `trajectory` en el estado con latencia por nodo, eventos, retries, bloqueos de seguridad y uso de tokens (cuando el provider lo devuelve).

- [x] **Documentar teoría -> evidencia en código.**  
  Se agregaron secciones explícitas en `README.md` y `REPORT.md`.

## Faltantes de evidencia de entrega (prioridad alta)

- [ ] **Generar y guardar evidencia real de demo en `demo/evidence/`.**  
  `demo/DEMO.md` y `demo/run_demo.sh` lo contemplan, pero en el repo no hay evidencia generada actualmente (JSON de corrida) para respaldar la demo pedida.


