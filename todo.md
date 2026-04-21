# TODO de entrega (alineado a `task.md`)

Checklist operativo para cerrar la entrega del TP multiagentes.

## 1) Requisitos mandatorios

- [x] LangGraph implementado con nodos/aristas/ruteo explícito.
- [x] Exactamente 2 agentes especializados en uso real:
  - [x] `Schema Agent`
  - [x] `Query Agent`
- [x] Separación clara por responsabilidades, prompts, tools y nodos de grafo.
- [x] HITL presente en flujo de documentación de schema.
- [x] MCP tools integradas en el workflow:
  - [x] inspección de schema
  - [x] ejecución SQL read-only
- [x] SQL ejecutada en modo seguro (sin DDL/DML en el path de ejecución).

## 2) Flujo A — Schema documentation (HITL)

- [ ] Conexión a PostgreSQL funcionando. *(validar en corrida final)*
- [x] Descubrimiento de schema (tablas, columnas, PK/FK, constraints donde aplique).
- [x] Draft de descripciones en lenguaje natural por tabla/columna.
- [x] Pedido de revisión humana cuando hay ambigüedad.
- [ ] Aprobación/corrección humana aplicada. *(validar evidencia de sesión)*
- [x] Persistencia de descripciones/contexto aprobados.
- [x] Reuso de esas descripciones en el flujo de queries.

## 3) Flujo B — Querying (NL → SQL)

- [x] Recibir pregunta en lenguaje natural.
- [x] Determinar intención + tablas/campos relevantes.
- [x] Generar SQL válida de lectura.
- [x] Validar seguridad/guardrails antes de ejecutar.
- [x] Ejecutar y devolver:
  - [x] SQL producida
  - [x] sample/preview de resultados
  - [x] explicación breve + limitaciones
- [x] Soporte de refinamiento iterativo (follow-up) en la misma sesión.

## 4) Memoria

- [x] Memoria persistente implementada y usada:
  - [x] preferencias de usuario entre sesiones
  - [x] descripción/contexto de schema aprobado
- [x] Memoria short-term implementada y usada:
  - [x] última pregunta
  - [x] último SQL draft/ejecutado
  - [x] supuestos/clarificaciones
  - [x] filtros/tablas recientes
- [x] README documenta qué se guarda y por qué (impacto en calidad de respuesta).

## 5) Observabilidad y robustez

- [x] Logs de transición de nodos de grafo.
- [x] Logs de llamadas MCP (tool, duración, resultado/error).
- [x] Logs de retry/fallback.
- [x] Logs de interacciones HITL.
- [x] Manejo robusto de errores:
  - [x] SQL inválida
  - [x] resultado vacío
  - [x] schema mismatch
  - [x] intención ambigua
  - [x] MCP/DB no disponible

## 6) Dataset requerido (DVD Rental)

- [ ] Dataset DVD Rental cargado en PostgreSQL. *(validar en entorno final)*
- [ ] Verificación de objetos de schema antes de correr agentes. *(validar en demo final)*
- [ ] Todos los escenarios de demo corren sobre DVD Rental. *(cerrar con evidencia)*

## 7) Entregables

### 7.1 README

- [x] Diagrama de arquitectura de los dos agentes/grafos.
- [x] Instrucciones exactas de setup y ejecución.
- [x] Diseño de memoria (persistente vs short-term).
- [x] MCP tools usadas y su rol.
- [x] Patrones de agentes aplicados.

### 7.2 Demo script

- [x] 1 sesión de schema con corrección humana.
- [x] 3 ejemplos de consultas NL distintas.
- [x] 1 ejemplo de follow-up refinement.
- [ ] Evidencia de ejecución sobre DVD Rental. *(confirmar capturas/logs finales)*

### 7.3 Reporte corto

- [ ] `REPORT.md` (1-2 páginas) con decisiones de diseño y trade-offs.

## 8) Calidad final antes de entregar

- [ ] Tests verdes (`pytest`). *(correr suite final y guardar output)*
- [ ] Lint/format verdes (`ruff`). *(correr checks finales)*
- [ ] Revisar que no haya archivos basura en commit:
  - [ ] `.DS_Store` removido
  - [ ] archivos temporales/locales removidos
- [ ] Verificar que no se suban secretos en `.env`.
- [ ] Revisión final de consistencia entre código, README y demo.

## 9) Prioridad sugerida

1. [ ] Cerrar `REPORT.md`.
2. [ ] Correr demo end-to-end y guardar evidencia.
3. [ ] Ejecutar tests/lint finales.
4. [ ] Armar commits limpios (código vs docs) y revisar diff final.
