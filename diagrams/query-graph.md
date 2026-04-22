# Diagrama del Query Graph

Orden real del grafo (`build_query_graph` en `src/graph/query_workflow.py`): primero corre el router de intención con capa determinística y fallback LLM para casos ambiguos; luego planner (heurístico + fallback opcional) y recién después `QueryAgent` para draft SQL.

```mermaid
flowchart TD
    A([START]) --> R[Router]
    R --> L[Cargar contexto]
    L --> I[Intents basicos - deterministico]
    I --> IFB[Intent fallback LLM - ambiguos]

    I -->|No ambiguo: no data query| Z([END])
    I -->|No ambiguo: data query| P[Planner: build_plan]
    IFB -->|No data query| Z
    IFB -->|data_query con confianza| P

    P --> PF[Planner fallback LLM - confidence below threshold - opcional]
    PF -->|needs_clarification o query_blocked| Z
    PF -->|Plan listo| S[Executor: QueryAgent → SQL]

    S --> V[Validar SQL]

    V -->|Retry| S
    V -->|Bloqueado / CLARIFY| Z
    V -->|OK| E[Ejecutar SQL MCP]

    E --> X[Explicar resultado]
    X --> M[Memoria short-term + trajectory]
    M --> Z

    classDef io fill:#E3F2FD,stroke:#1E88E5,color:#0D47A1,stroke-width:1px;
    classDef step fill:#F3E5F5,stroke:#8E24AA,color:#4A148C,stroke-width:1px;
    classDef decision fill:#FFF3E0,stroke:#FB8C00,color:#E65100,stroke-width:1px;
    classDef exec fill:#E8F5E9,stroke:#43A047,color:#1B5E20,stroke-width:1px;
    classDef planner fill:#E1F5FE,stroke:#0277BD,color:#01579B,stroke-width:1px;

    class A,Z io;
    class R,L,IFB,PF,S,E,X,M step;
    class I,V decision;
    class E exec;
    class P planner;
```
