# Diagrama de arquitectura

Vista de componentes: el **Query Workflow** encadena planner heurístico (`build_plan`) → **Query Agent** (NL→SQL con `query_plan` en contexto) → **Validator**. El **Schema Workflow** usa **`draft_bundle`** y persiste **`semantic_descriptions`** junto al contexto. MCP centraliza schema + SQL read-only.

```mermaid
flowchart LR
    U[Usuario] --> UI[UI WebUI y Schema]
    UI --> API[API FastAPI]

    API --> QW[Query Workflow LangGraph]
    QW --> PL[Planner build_plan]
    PL --> QA[Query Agent executor]
    QA --> VAL[Validator + sql_safety]

    API --> SW[Schema Workflow LangGraph]
    SW --> SA[Schema Agent draft_bundle]

    QW --> MCPC[MCP Client]
    SW --> MCPC
    MCPC --> MCPS[MCP Server]
    MCPS --> DB[(PostgreSQL DVD Rental)]

    API --> P[(Persistencia JSON)]
    QW --> S[(SessionStore RAM)]
    SW --> P

    P --> CTX[schema_context: markdown + catalog + semantic_descriptions]

    classDef ext fill:#E3F2FD,stroke:#1E88E5,color:#0D47A1,stroke-width:1px;
    classDef workflow fill:#F3E5F5,stroke:#8E24AA,color:#4A148C,stroke-width:1px;
    classDef agent fill:#E8F5E9,stroke:#43A047,color:#1B5E20,stroke-width:1px;
    classDef planner fill:#E1F5FE,stroke:#0277BD,color:#01579B,stroke-width:1px;
    classDef mcp fill:#FFF3E0,stroke:#FB8C00,color:#E65100,stroke-width:1px;
    classDef data fill:#ECEFF1,stroke:#546E7A,color:#263238,stroke-width:1px;

    class U,UI,API ext;
    class QW,SW workflow;
    class QA,VAL,SA agent;
    class PL planner;
    class MCPC,MCPS mcp;
    class DB,P,S,CTX data;
```
