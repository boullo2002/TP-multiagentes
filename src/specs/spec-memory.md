# Specification — Memory (Persistent + Short-term)

> **Purpose:** Define what is stored in each memory type and why, matching the TP requirement.

---

## 1. Persistent memory (cross-session)

### 1.1 What to store (minimum)

Store user preferences across sessions:

- `preferred_language` (default: `"es"`)
- `preferred_output_format` (`"table"` or `"json"`, default `"table"`)
- `preferred_date_format` (default `"YYYY-MM-DD"`)
- `sql_safety_strictness` (`"strict"` default)
- `default_limit` (default `50`)

### 1.2 Storage implementation

Use a simple persistent store under `DATA_DIR`:

- `DATA_DIR/user_preferences.json`

Or SQLite if preferred, but JSON is acceptable and simplest.

### 1.3 Why it matters

These preferences influence:

- output formatting
- language (Spanish)
- default LIMIT behavior
- how often the system asks for HITL approvals

---

## 2. Schema context store (persistent artifact)

Schema context approved via HITL is persisted in:

- `DATA_DIR/schema_context.json`

Include:

- generated_at timestamp
- version integer
- `context_markdown` (human-readable, Query-Agent-oriented context)
- ambiguity `questions` + captured `answers` (when needed)

Why:

- Query Agent must reuse the approved context artifact to improve NL→SQL correctness and explainability.

---

## 3. Short-term memory (session continuity)

### 3.1 What to store (minimum)

Keep session context for follow-ups:

- last user question
- last SQL draft + last SQL executed
- recent tables
- recent filters (dates, categories)
- open assumptions / clarifications requested
- last result preview (optional reference)

### 3.2 Storage implementation

Short-term memory is stored in:

- LangGraph state (`short_term` field)
- optionally also in an in-memory `SessionStore` keyed by `session_id`

### 3.3 Why it matters

Enables follow-ups like:

- “Ahora solo para 2006”
- “Ordenalo descendente”
- “Mostrame top 10”

---

## 4. Acceptance criteria

1. Preferences persist across app restarts (container restart).
2. Short-term memory affects follow-up queries within a session.
3. README documents what is stored and why for both memory types.

