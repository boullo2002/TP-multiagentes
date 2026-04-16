from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")

    base_url: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_BASE_URL", "LLM_SERVICE_URL"),
    )
    api_key: str = Field(default="")
    model: str = Field(default="gpt-4")
    # Segundos; evita que el grafo quede colgado si el proxy LLM no responde.
    request_timeout: float = Field(default=120.0, ge=5.0, le=900.0)


class LangSmithSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LANGSMITH_", extra="ignore")

    tracing: bool = Field(default=False)
    endpoint: str = Field(default="https://api.smith.langchain.com")
    api_key: str = Field(default="")
    project: str = Field(default="tp-multiagentes")


class GraphSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRAPH_", extra="ignore")

    max_iterations: int = Field(default=12, ge=1, le=50)
    # Pasos del grafo (nodos + reintentos); no confundir con max_iterations de bucles ReAct.
    recursion_limit: int = Field(default=64, ge=16, le=500)


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    api_host: str = Field(default="0.0.0.0", validation_alias="API_HOST")
    api_port: int = Field(default=8000, validation_alias="API_PORT")
    environment: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="ENVIRONMENT"
    )


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    server_url: str = Field(default="http://mcp:7000", validation_alias="MCP_SERVER_URL")
    request_timeout_ms: int = Field(default=120_000, validation_alias="MCP_REQUEST_TIMEOUT_MS")


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    data_dir: str = Field(default="/app/data", validation_alias="DATA_DIR")


class SafetySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    default_limit: int = Field(default=50, validation_alias="DEFAULT_LIMIT")
    sql_safety_strictness: Literal["strict", "balanced"] = Field(
        default="strict", validation_alias="SQL_SAFETY_STRICTNESS"
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    llm: LLMSettings = LLMSettings()
    langsmith: LangSmithSettings = LangSmithSettings()
    graph: GraphSettings = GraphSettings()
    # Fuera de GraphSettings para evitar el env automático GRAPH_QUERY_SQL_RETRY_MAX.
    query_sql_retry_max: int = Field(default=2, validation_alias="QUERY_SQL_RETRY_MAX", ge=0, le=10)
    app: ApplicationSettings = ApplicationSettings()
    mcp: MCPSettings = MCPSettings()
    storage: StorageSettings = StorageSettings()
    safety: SafetySettings = SafetySettings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
