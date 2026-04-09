# Weekend Planner AI Agent - Project Specification

## Overview

This specification document outlines the development of a Weekend Planner AI Agent - a single-user application that helps manage weekend activities through an intelligent agent system. The agent will search for activities, schedule them in an agenda, and follow up on Monday to gather feedback about the weekend experience.

## Project Goals

The primary goal is to develop an AI agent that:

1. **Activity Discovery**: Searches for weekend activities (events, restaurants, outdoor activities, entertainment)
2. **Activity Scheduling**: Manages scheduling of activities in the user's agenda
3. **Weather Integration**: Considers weather conditions when suggesting activities
4. **Monday Follow-up**: Proactively asks the user about their weekend experience on Monday
5. **Single User Experience**: Provides personalized weekend planning without authentication complexity

## Technology Stack

- **LLM Framework**: LangChain (ReAct agent pattern)
- **Model Abstraction**: LiteLLM SDK (single abstraction layer - all providers hidden behind LiteLLM)
- **API Framework**: FastAPI
- **LLM Endpoint**: LangServe
- **Frontend**: OpenAIWeb
- **Database**: PostgreSQL (persistence)
- **Orchestration**: Docker Compose
- **Observability**: LangSmith
- **Testing**: pytest (unit and functional tests)
- **Package Management**: uv (Python)

**Important**: LiteLLM is the ONLY interface for LLM interactions. Provider-specific SDKs (OpenAI, Anthropic, etc.) must NOT be installed or imported directly in the codebase.

## Architecture Overview

```
┌─────────────┐
│  OpenAIWeb  │  Frontend Interface
│  Frontend   │
└──────┬──────┘
       │ HTTP/REST
┌──────▼──────────────────────────┐
│      FastAPI Server             │
│  ┌──────────────────────────┐   │
│  │    LangServe Endpoint    │   │
│  └──────┬───────────────────┘   │
│         │                       │
│  ┌──────▼───────────────────┐   │
│  │  LangChain ReAct Agent   │   │
│  │  - Thought/Action/Obs    │   │
│  └──────┬───────────────────┘   │
│         │                       │
│  ┌──────▼───────────────────┐   │
│  │      Agent Tools         │   │
│  │  - Web Search            │   │
│  │  - Weather API           │   │
│  │  - Agenda Access         │   │
│  └────────┬─────────────────┘   │
└───────────┼─────────────────────┘
            │
    ┌───────┴────────┐
    │                │
┌───▼────┐    ┌─────▼─────┐
│Postgres│    │ LangSmith │
│Database│    │ Observab. │
└────────┘    └───────────┘
```

## Agent Tools Specification

### 1. Web Search Tool

- **Purpose**: Search for weekend activities, events, restaurants, entertainment options
- **Implementation**: Use a web search API (e.g., Tavily, DuckDuckGo, or Serper API)
- **Input**: Search query with activity type, location, date preferences
- **Output**: List of relevant activities with details (name, location, time, description, price range if available)

### 2. Weather Tool

- **Purpose**: Get weather forecasts for weekend dates to inform activity suggestions
- **Implementation**: OpenWeatherMap API (default, configurable)
- **Input**: Location, date range (Saturday-Sunday)
- **Output**: Weather forecast (temperature, conditions, precipitation probability)
- **Integration**: Agent uses weather to suggest appropriate activities (e.g., outdoor vs indoor)

### 3. Agenda Access Tool (Custom)

- **Purpose**: CRUD operations for user's weekend agenda
- **Implementation**: Custom FastAPI endpoints with PostgreSQL backend
- **Operations**:
  - `create_event`: Add new activity to agenda
  - `read_events`: Retrieve scheduled activities for date range
  - `update_event`: Modify existing activity
  - `delete_event`: Remove activity from agenda
- **Data Model**:
  ```python
  {
    "id": "uuid",
    "title": "string",
    "description": "string",
    "start_time": "datetime",
    "end_time": "datetime",
    "location": "string",
    "activity_type": "event|restaurant|outdoor|entertainment|custom",
    "weather_dependent": "boolean",
    "created_at": "datetime",
    "updated_at": "datetime"
  }
  ```


## Data Persistence

### PostgreSQL Schema

**Tables:**

1. **activities** - Scheduled weekend activities

   - id (UUID, primary key)
   - title (VARCHAR)
   - description (TEXT)
   - start_time (TIMESTAMP)
   - end_time (TIMESTAMP)
   - location (VARCHAR)
   - activity_type (VARCHAR)
   - weather_dependent (BOOLEAN)
   - created_at (TIMESTAMP)
   - updated_at (TIMESTAMP)

2. **user_preferences** - User preferences for activity suggestions

   - id (UUID, primary key)
   - preference_key (VARCHAR, unique)
   - preference_value (JSONB)
   - updated_at (TIMESTAMP)

3. **weekend_feedback** - Monday follow-up feedback

   - id (UUID, primary key)
   - weekend_date (DATE)  -- Saturday date of the weekend
   - feedback_text (TEXT)
   - rating (INTEGER, 1-5)
   - submitted_at (TIMESTAMP)

## Implementation Phases

### Phase 0: Project Setup and Foundation

**Goal**: Establish project structure, Docker setup, and basic configuration

**Steps:**

1. Initialize Python project with `uv`
2. Create Docker Compose configuration:brew install pantsbuild/tap/pants
   - PostgreSQL service
   - FastAPI application service
   - Environment variable setup

3. Set up project structure:
   ```
   weekend-planner/
   ├── src/
   │   ├── agent/
   │   ├── tools/
   │   ├── api/
   │   ├── models/
   │   └── config/
   ├── tests/
   │   ├── unit/
   │   └── functional/
   ├── docker/
   ├── docker-compose.yml
   ├── .env.example
   ├── pyproject.toml
   └── README.md
   ```

4. Configure `.env.example` with all required variables
5. Set up pytest configuration
6. Initialize git repository (if not exists)

**Testing:**

- Unit: Test Docker Compose services start correctly
- Functional: Verify PostgreSQL connection, verify FastAPI health endpoint

**Documentation:**

- Update README with setup instructions
- Document environment variables

---

### Phase 1: LLM Integration with LangChain and Observability

**Goal**: Set up LangChain with LiteLLM, implement basic agent structure, and enable LangSmith observability

**Critical Architecture Constraint**: All LLM interactions MUST go through LiteLLM. The codebase must NEVER import or directly use provider-specific SDKs (e.g., `openai`, `anthropic`). LiteLLM is the single abstraction layer that hides all model and provider differences.

**Steps:**

1. Install dependencies (langchain, litellm, langsmith)

   - Do NOT install provider-specific SDKs (openai, anthropic, etc.)

2. Configure LiteLLM to support multiple models (configurable via env)

   - Use LiteLLM's unified interface for all model calls
   - Configure via `LITELLM_MODEL` environment variable (e.g., `gpt-4`, `claude-3-5-sonnet`, `gpt-3.5-turbo`)
   - API keys configured through LiteLLM's standard environment variables

3. Create LLM wrapper/utility that uses only LiteLLM

   - This wrapper will be the single point of LLM access in the codebase
   - No provider-specific code anywhere

4. Create basic LangChain ReAct agent structure using LiteLLM
5. Configure LangSmith for observability (tracing, monitoring)
6. Implement simple agent that can respond to basic queries
7. Add observation step after first LLM call for debugging

**Testing:**

- Unit: Test agent initialization, test LLM configuration through LiteLLM, test LangSmith connection
- Functional: Test agent responds to simple queries, verify traces appear in LangSmith
- Verify no provider-specific imports exist in codebase

**Documentation:**

- Document LangSmith setup and usage
- Document LiteLLM model configuration (all models accessed via LiteLLM)
- Document that providers are abstracted and hidden
- Add examples of agent interactions
- Document supported models via LiteLLM

---

### Phase 2: Web Search Tool

**Goal**: Implement and integrate web search capability

**Steps:**

1. Choose and configure web search API (Tavily recommended, with fallback to DuckDuckGo)
2. Create web search tool class implementing LangChain tool interface
3. Integrate tool into agent
4. Add error handling and rate limiting
5. Implement result parsing and formatting

**Testing:**

- Unit: Mock API responses, test parsing logic, test error handling
- Functional: Test actual search queries, verify results format, test rate limiting

**Documentation:**

- Document search tool API configuration
- Add examples of search queries and results
- Document rate limits and error handling

---

### Phase 3: Weather Tool

**Goal**: Implement weather API integration

**Steps:**

1. Set up OpenWeatherMap API integration (or configurable alternative)
2. Create weather tool class implementing LangChain tool interface
3. Integrate tool into agent
4. Add caching mechanism (avoid repeated API calls for same date/location)
5. Format weather data for agent consumption

**Testing:**

- Unit: Mock weather API, test data parsing, test caching logic
- Functional: Test real weather queries, verify caching works, test error handling

**Documentation:**

- Document weather API setup
- Document weather data format
- Add examples of weather queries

---

### Phase 4: Database Schema and Agenda Access Tool

**Goal**: Implement PostgreSQL schema and agenda management tool

**Steps:**

1. Create Alembic migrations for database schema
2. Implement SQLAlchemy models for activities, preferences, feedback
3. Create FastAPI endpoints for agenda CRUD operations
4. Create agenda access tool class implementing LangChain tool interface
5. Integrate tool into agent
6. Add data validation and error handling

**Testing:**

- Unit: Test database models, test CRUD operations, test validation logic
- Functional: Test API endpoints, test agent can create/read/update/delete activities, test data persistence

**Documentation:**

- Document database schema
- Document API endpoints
- Add examples of agenda operations

---

### Phase 5: ReAct Agent Logic and Activity Planning

**Goal**: Implement core agent reasoning for weekend planning

**Steps:**

1. Define agent prompts for activity discovery
2. Implement reasoning logic:

   - User query understanding
   - Activity search strategy
   - Weather-aware suggestions
   - Schedule conflict detection
   - Activity recommendation ranking

3. Implement agent workflow:

   - Analyze user request
   - Search for activities
   - Check weather
   - Suggest activities
   - Schedule selected activities

4. Add conversation memory/history

**Testing:**

- Unit: Test prompt templates, test reasoning logic components
- Functional: End-to-end test of activity planning workflow, test weather-aware suggestions, test conflict detection

**Documentation:**

- Document agent reasoning flow
- Add examples of weekend planning conversations
- Document prompt engineering decisions

---

### Phase 6: Monday Follow-up Feature

**Goal**: Implement Monday follow-up functionality

**Steps:**

1. Create scheduled task mechanism (APScheduler or similar)
2. Implement Monday detection logic
3. Create follow-up prompt for gathering feedback
4. Implement feedback storage
5. Integrate with agent for follow-up conversations
6. Add user preference learning from feedback

**Testing:**

- Unit: Test Monday detection, test feedback storage, test preference updates
- Functional: Test scheduled follow-up triggers, test feedback collection flow, test preference learning

**Documentation:**

- Document follow-up mechanism
- Add examples of follow-up conversations
- Document preference learning logic

---

### Phase 7: LangServe Integration and API Endpoints

**Goal**: Expose agent via LangServe and create FastAPI endpoints

**Steps:**

1. Configure LangServe to serve the agent
2. Create FastAPI endpoints:

   - `/chat` - Main conversation endpoint
   - `/agent/invoke` - Direct agent invocation
   - `/agenda` - Agenda management endpoints
   - `/health` - Health check

3. Add request/response models
4. Implement error handling middleware
5. Add API documentation (OpenAPI/Swagger)

**Testing:**

- Unit: Test endpoint handlers, test request validation
- Functional: Test all API endpoints, test error responses, test API documentation

**Documentation:**

- Document all API endpoints
- Add API usage examples
- Document authentication (if any) and rate limiting

---

### Phase 8: OpenAIWeb Frontend Integration

**Goal**: Integrate OpenAIWeb frontend for user interaction

**Steps:**

1. Configure OpenAIWeb to connect to LangServe endpoint
2. Customize frontend branding/messaging
3. Test end-to-end user experience
4. Add frontend error handling

**Testing:**

- Functional: Test complete user workflow through frontend, test error scenarios, test responsiveness

**Documentation:**

- Document frontend setup
- Add screenshots or demo video
- Document user guide

---

### Phase 9: Testing, Documentation, and Polish

**Goal**: Comprehensive testing, documentation, and final improvements

**Steps:**

1. Increase test coverage (aim for >80%)
2. Add integration tests for full workflows
3. Performance testing and optimization
4. Security review
5. Complete all documentation:

   - README with full setup guide
   - API documentation
   - Architecture documentation
   - Deployment guide

6. Code cleanup and refactoring
7. Add logging and monitoring improvements

**Testing:**

- Unit: Achieve comprehensive coverage
- Functional: All user workflows tested
- Integration: Full system integration tests
- Performance: Load testing

**Documentation:**

- Complete all documentation sections
- Add troubleshooting guide
- Add contribution guidelines

## Environment Variables

Required environment variables (stored in `.env`):

```bash
# LLM Configuration (via LiteLLM - abstracts all providers)
LITELLM_MODEL=gpt-4  # LiteLLM model identifier (e.g., gpt-4, claude-3-5-sonnet, gpt-3.5-turbo)
# Provider API keys (LiteLLM will use the appropriate one based on model)
OPENAI_API_KEY=your_openai_key  # For OpenAI models
# ANTHROPIC_API_KEY=your_anthropic_key  # For Anthropic models (if using Claude)
# Add other provider keys as needed (all accessed through LiteLLM)

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=weekend-planner

# Database
DATABASE_URL=postgresql://user:password@postgres:5432/weekend_planner
POSTGRES_USER=user
POSTGRES_PASSWORD=password
POSTGRES_DB=weekend_planner

# Weather API
WEATHER_API_KEY=your_openweathermap_key
WEATHER_API_PROVIDER=openweathermap  # or alternative

# Web Search API
SEARCH_API_KEY=your_search_api_key  # Tavily, Serper, etc.
SEARCH_API_PROVIDER=tavily  # or duckduckgo, serper

# Application
API_HOST=0.0.0.0
API_PORT=8000
ENVIRONMENT=development
```

## Suggested Additional Features

1. **User Preferences Learning**: Store and learn from user activity preferences over time
2. **Activity Recommendations**: Proactive suggestions based on past activities and preferences
3. **Budget Awareness**: Consider price ranges when suggesting activities
4. **Location Intelligence**: Learn user's preferred locations and travel radius
5. **Calendar Sync**: Optional integration with external calendars (Google Calendar, etc.)
6. **Activity Reminders**: Send reminders before scheduled activities
7. **Weekend Summary**: Generate weekend summary on Sunday evening
8. **Multi-weekend Planning**: Plan multiple weekends in advance
9. **Activity Rating System**: Rate activities for better future recommendations
10. **Social Sharing**: Share weekend plans (if desired in future)

## Success Criteria

The project will be considered successful when:

1. ✅ Agent can discover weekend activities using web search
2. ✅ Agent considers weather when suggesting activities
3. ✅ Agent can schedule activities in user's agenda
4. ✅ Agent proactively asks about weekend on Monday
5. ✅ All tools are functional and integrated
6. ✅ Observability is working with LangSmith
7. ✅ Application runs via Docker Compose
8. ✅ Test coverage >80%
9. ✅ Complete documentation exists
10. ✅ User can interact via OpenAIWeb frontend

## Development Workflow

For each phase:

1. **Implement** the phase features
2. **Write tests** (unit and functional)
3. **Run tests** and ensure all pass
4. **Update documentation**
5. **Verify goal alignment** - ensure the implementation serves the project goals
6. **Code review** - self-review for quality and best practices
7. **Fix linting/formatting** with `uv run ruff check --fix && uv run ruff format`
8. **Proceed** to next phase only after current phase is complete

## Notes

- Each phase should be completed with tests and documentation before moving to the next
- The observation step after Phase 1 LLM implementation is critical for debugging
- Always verify that implementations align with the project goals
- Use `uv` for all Python package management
- Use `pytest` with plain functions (not classes) for testing
- Follow Given/When/Then/Clean pattern for tests

## Architecture Constraints

**LiteLLM as Single Abstraction Layer:**

- All LLM calls must go through LiteLLM only
- Never import provider-specific SDKs (e.g., `openai`, `anthropic`, `google.generativeai`)
- Never use provider-specific classes or functions directly
- LiteLLM handles all provider differences, authentication, and model switching
- Model switching is done purely via configuration (environment variables)
- The codebase should be provider-agnostic - changing providers should only require config changes