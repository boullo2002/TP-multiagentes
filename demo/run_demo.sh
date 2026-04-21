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

chat_payload() {
  # JSON via Python: evita roturas de comillas y que fragmentos del payload se interpreten como comandos.
  DEMO_MODEL="$MODEL" DEMO_PROMPT="$1" python3 - <<'PY'
import json, os
print(
    json.dumps(
        {
            "model": os.environ["DEMO_MODEL"],
            "messages": [{"role": "user", "content": os.environ["DEMO_PROMPT"]}],
        },
        ensure_ascii=False,
    )
)
PY
}

call_chat() {
  local name="$1"
  local prompt="$2"
  local out_file="${RUN_DIR}/${name}.json"
  local attempt max=3
  echo "[chat] ${name}: ${prompt}"
  for attempt in $(seq 1 "${max}"); do
    curl -sS "${API_BASE_URL}/v1/chat/completions" \
      -H 'content-type: application/json' \
      -d "$(chat_payload "${prompt}")" \
      > "${out_file}"
    if DEMO_OUT="${out_file}" python3 - <<'PY'
import json, os, sys
path = os.environ["DEMO_OUT"]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
bad = "problema interno" in text or "internal problem" in text.lower()
sys.exit(1 if bad else 0)
PY
    then
      break
    fi
    if [[ "${attempt}" -lt "${max}" ]]; then
      echo "     reintento $((attempt + 1))/${max} (respuesta generica de error)..."
      sleep 3
    fi
  done
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
  -d "$(python3 -c "import json; print(json.dumps({'answers': {'q_demo': 'Para ranking de peliculas, usar rentals como popularidad.'}}))")" \
  > "${RUN_DIR}/schema-answer.json"
echo "saved -> ${RUN_DIR}/schema-answer.json"
# Tras regenerar schema + LLM, la primera consulta NL a veces falla por contención; damos un respiro al backend.
sleep 2

step "Queries"
# Importante: el follow-up usa memoria de sesión (session_id default + SessionStore).
# Debe ir justo despues de la consulta que refina; si se intercala otra NL, last_sql apunta a otra cosa.
call_chat "q1_total_peliculas" "cuantas peliculas hay en total?"
call_chat "q2_top_5_mas_vistas" "dame las 5 peliculas mas vistas"
call_chat "q3_followup_2006" "ahora solo las de 2006"
call_chat "q4_top_5_actores" "top 5 actores con mas peliculas"

step "Summary"
python - <<'PY' "${RUN_DIR}"
import json, os, sys
run_dir = sys.argv[1]
files = [
    "q1_total_peliculas.json",
    "q2_top_5_mas_vistas.json",
    "q3_followup_2006.json",
    "q4_top_5_actores.json",
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
