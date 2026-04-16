FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml /app/pyproject.toml

# Install dependencies (no dev) first for caching
RUN uv sync --frozen --no-dev || uv sync --no-dev

COPY src /app/src
COPY schema_agent_front /app/schema_agent_front
COPY spec.md /app/spec.md

ENV PYTHONPATH=/app/src

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=20 CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uv", "run", "uvicorn", "api.main:get_app", "--host", "0.0.0.0", "--port", "8000"]

