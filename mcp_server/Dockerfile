FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml /app/pyproject.toml
RUN uv sync --frozen --no-dev || uv sync --no-dev

COPY mcp_server /app/mcp_server

ENV PYTHONPATH=/app
EXPOSE 7000

CMD ["uv", "run", "uvicorn", "mcp_server.server:get_app", "--host", "0.0.0.0", "--port", "7000"]

