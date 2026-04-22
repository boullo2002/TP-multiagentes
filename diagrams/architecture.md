# Diagrama de arquitectura

Este diagrama muestra solo la arquitectura **a nivel de bloques**. El detalle de nodos/rutas internas vive en los diagramas específicos de cada workflow.

```mermaid
flowchart LR
    U[Usuario] --> UI[UI WebUI y Schema]
    UI --> API[API FastAPI]

    subgraph QW[Query Workflow — LangGraph]
        direction TB
        Q0[Orquestación NLQ→SQL<br/>Ver query graph]
    end

    subgraph SW[Schema Workflow — LangGraph]
        direction TB
        S0[Orquestación schema + HITL<br/>Ver schema graph]
    end

    API --> Q0
    API --> S0

    Q0 --> MCPC[MCP Client]
    S0 --> MCPC
    MCPC --> MCPS[MCP Server]
    MCPS --> DB[(PostgreSQL DVD Rental)]

    API --> P[(Persistencia JSON)]
    Q0 --> SESS[(SessionStore RAM)]

    P --> CTX[schema_context: markdown + catalog + semantic_descriptions]

    classDef ext fill:#E3F2FD,stroke:#1E88E5,color:#0D47A1,stroke-width:1px;
    classDef subgraphBox fill:#F3E5F5,stroke:#8E24AA,color:#4A148C,stroke-width:1px;
    classDef step fill:#EDE7F6,stroke:#7B1FA2,color:#4A148C,stroke-width:1px;
    classDef agent fill:#E8F5E9,stroke:#43A047,color:#1B5E20,stroke-width:1px;
    classDef planner fill:#E1F5FE,stroke:#0277BD,color:#01579B,stroke-width:1px;
    classDef mcp fill:#FFF3E0,stroke:#FB8C00,color:#E65100,stroke-width:1px;
    classDef data fill:#ECEFF1,stroke:#546E7A,color:#263238,stroke-width:1px;
    classDef persist fill:#E8F5E9,stroke:#2E7D32,color:#1B5E20,stroke-width:1px;

    class U,UI,API ext;
    class QW,SW subgraphBox;
    class Q0,S0 step;
    class MCPC,MCPS mcp;
    class DB,P,SESS,CTX data;
```

Detalle interno:

- Query Workflow: ver diagrama de query graph.
- Schema Workflow: ver diagrama de schema graph.
