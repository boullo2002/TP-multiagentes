# Specification — Two Agents (Schema Agent + Query Agent)

> **Purpose:** Define the responsibilities, prompts, and boundaries for exactly two specialized agents as required by the TP.

---

## 1. Two-agent requirement (strict)

You must implement **exactly two** specialized agents:

1. **Schema Agent**
2. **Query Agent**

They must be clearly separated by:

- responsibilities
- prompts
- tools usage (MCP tool calls)
- graph nodes

---

## 2. Schema Agent

### 2.1 Responsibilities

- Inspect DB schema metadata via MCP schema tool.
- Draft natural language descriptions:
  - per table
  - per column
  - relationships summary (PK/FK)
- Trigger HITL checkpoints before committing/persisting descriptions.
- Persist **approved** schema descriptions for reuse by Query Agent.

### 2.2 Inputs

- `schema_metadata` from MCP tool
- existing descriptions from persistent store
- user preferences (language, detail level)

### 2.3 Outputs

- `schema_descriptions_draft` (before HITL)
- `schema_descriptions` persisted artifact (after HITL)

### 2.4 Prompt requirements (in `src/agents/prompts.py`)

Provide:

- a system prompt for the Schema Agent emphasizing:
  - “do not invent columns/relationships”
  - “if ambiguous, ask for confirmation”
  - “write short, query-useful descriptions”
  - Spanish output by default

---

## 3. Query Agent

### 3.1 Responsibilities

- Interpret natural language questions.
- Use:
  - MCP schema metadata (when needed)
  - approved schema descriptions
  - short-term memory context
  - user preferences (output format)
- Apply Planner/Executor decomposition:
  - Planner: explicit plan
  - Executor: SQL draft
- Apply Critic/Validator before execution:
  - safety checks
  - schema match checks
  - “riskiness” classification
- Trigger HITL checkpoint before executing risky queries.
- Execute validated SQL via MCP SQL tool (read-only).
- Explain results and support iterative refinement.

### 3.2 Inputs

- user question (chat message)
- `schema_descriptions`
- `schema_metadata` (cached or retrieved)
- `short_term` (last SQL, last filters, assumptions)
- `user_preferences`

### 3.3 Outputs

- `query_plan`
- `sql_draft`
- `sql_validated`
- `query_result`
- final assistant message including SQL + preview + explanation

### 3.4 Prompt requirements

Provide:

- a system prompt for Query Agent emphasizing:
  - always produce read-only SQL
  - default LIMIT usage (or ask if user wants full results)
  - explain assumptions
  - ask clarifying questions when necessary
  - Spanish output by default

---

## 4. Planner/Executor (explicit)

Implement as separate functions/classes/modules:

- `src/agents/planner.py`
- `src/agents/query_agent.py` (executor)

Planner output must be stored in graph state for traceability.

---

## 5. Critic/Validator (explicit)

Implement in `src/agents/validator.py`:

Input:

- `sql_draft`
- known schema metadata
- safety settings

Output:

- `is_safe: bool`
- `needs_human_approval: bool`
- `issues: list[str]`
- `suggested_sql: str | None` (optional auto-fix)

---

## 6. Acceptance criteria

- Exactly two agents exist and are used in the graph.
- Planner/Executor separation exists and is visible in code.
- Validator exists and runs before SQL execution.
- Schema Agent persists approved descriptions.
- Query Agent reuses persisted descriptions and short-term memory.

