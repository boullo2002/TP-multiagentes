#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
MODEL="${MODEL:-tp-multiagentes}"
OUT_DIR="${OUT_DIR:-demo/evidence}"
TS="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${OUT_DIR}/${TS}"

mkdir -p "${RUN_DIR}"

echo "[demo] API_BASE_URL=${API_BASE_URL}"
echo "[demo] MODEL=${MODEL}"
echo "[demo] output=${RUN_DIR}"

step() { echo; echo "==> $*"; }

call_chat() {
  local name="$1"
  local prompt="$2"
  local out_file="${RUN_DIR}/${name}.json"
  echo "[chat] ${name}: ${prompt}"
  curl -sS "${API_BASE_URL}/v1/chat/completions" \
    -H 'content-type: application/json' \
    -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"${prompt}\"}]}" \
    > "${out_file}"
  echo "     saved -> ${out_file}"
}

step "Health"
curl -fsS "${API_BASE_URL}/health" > "${RUN_DIR}/health.json"
echo "saved -> ${RUN_DIR}/health.json"

step "Schema state"
curl -sS "${API_BASE_URL}/schema-agent/state" > "${RUN_DIR}/schema-state-before.json"
echo "saved -> ${RUN_DIR}/schema-state-before.json"

step "Schema HITL answer (demo)"
curl -sS -X POST "${API_BASE_URL}/schema-agent/answer" \
  -H 'content-type: application/json' \
  -d '{"answers":{"q_demo":"Para ranking de peliculas, usar rentals como popularidad."}}' \
  > "${RUN_DIR}/schema-answer.json"
echo "saved -> ${RUN_DIR}/schema-answer.json"

step "Queries"
call_chat "q1_total_peliculas" "cuantas peliculas hay en total?"
call_chat "q2_top_5_mas_vistas" "dame las 5 peliculas mas vistas"
call_chat "q3_top_5_actores" "top 5 actores con mas peliculas"
call_chat "q4_followup_2006" "ahora solo las de 2006"

step "Summary"
python - <<'PY' "${RUN_DIR}"
import json, os, sys
run_dir = sys.argv[1]
files = [
    "q1_total_peliculas.json",
    "q2_top_5_mas_vistas.json",
    "q3_top_5_actores.json",
    "q4_followup_2006.json",
]
for fn in files:
    p = os.path.join(run_dir, fn)
    try:
        data = json.load(open(p, encoding="utf-8"))
        text = data["choices"][0]["message"]["content"]
        first = text.splitlines()[0] if isinstance(text, str) and text else "(sin contenido)"
        print(f"- {fn}: {first[:140]}")
    except Exception as e:
        print(f"- {fn}: ERROR leyendo respuesta ({e})")
PY

echo
echo "[demo] OK. Evidencia guardada en: ${RUN_DIR}"
echo "[demo] Tip: adjuntar estos JSON como evidencia de corrida reproducible."
