#!/usr/bin/env bash
# Comprueba GET /health del backend (spec-ui-openaiweb §4.1).
# Uso: ./ui/verify-backend.sh [API_BASE_URL]
# Ejemplo: ./ui/verify-backend.sh http://127.0.0.1:8000
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"
BASE="${BASE%/}"
if curl -fsS "${BASE}/health" >/dev/null; then
  echo "OK: ${BASE}/health responde."
  exit 0
fi
echo "FAIL: ${BASE}/health no responde (¿levantaste el servicio app?)" >&2
exit 1
