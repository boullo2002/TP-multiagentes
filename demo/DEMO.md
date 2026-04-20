# Demo Script Reproducible (DVD Rental)

Este guion cumple los entregables pedidos:

- 1 sesion de schema con correccion humana
- 3 consultas NL distintas
- 1 follow-up refinement
- evidencia de ejecucion sobre DVD Rental

## 0) Prerrequisitos

```bash
cp .env.example .env
docker compose up --build -d
```

Verificar servicios:

```bash
docker compose ps
```

Validar que la base es DVD Rental:

```bash
docker compose exec db psql -U dvd_user -d dvdrental -c "SELECT COUNT(*) AS total_films FROM film;"
```

Esperado: `total_films = 1000`.

---

## 1) Sesion de schema con correccion humana (HITL)

### 1.1 Estado del Schema Agent

```bash
curl -sS http://localhost:8000/schema-agent/state
```

Puntos a verificar en la respuesta JSON:

- `status` = `ready` o `needs_human`
- `schema_hash` presente
- si hay ambiguedad, `draft.questions` contiene preguntas

### 1.2 Correccion/aporte humano

Enviar una respuesta humana por API:

```bash
curl -sS -X POST http://localhost:8000/schema-agent/answer \
  -H 'content-type: application/json' \
  -d '{"answers":{"q_demo":"Para ranking de peliculas, usar rentals como popularidad."}}'
```

Resultado esperado:

- `status: "ready"`
- `context.answers.q_demo` guardado
- `approved_by_human: true`

> Alternativa UI: abrir `http://localhost:8000/schema-agent/ui` y responder ahi las preguntas.

---

## 2) Tres consultas NL distintas (OpenAI-compatible)

Formato base:

```bash
curl -sS http://localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{
    "model":"tp-multiagentes",
    "messages":[{"role":"user","content":"<tu pregunta>"}]
  }'
```

### Consulta 1

Pregunta:

`cuantas peliculas hay en total?`

Evidencia observada (resumen real):

- SQL: `SELECT COUNT(*) AS total_movies FROM film LIMIT 50;`
- Resultado: 1 fila
- Valor: `1000`

### Consulta 2

Pregunta:

`dame las 5 peliculas mas vistas`

Evidencia observada (resumen real):

- SQL con joins `film -> inventory -> rental`
- Orden por conteo de rentals desc y `LIMIT 5`
- Top visto incluye `Bucket Brotherhood` (34), `Rocketeer Mother` (33)

### Consulta 3

Pregunta:

`top 5 actores con mas peliculas`

Evidencia observada (resumen real):

- SQL con join `actor` + `film_actor`
- `COUNT(fa.film_id)` por actor
- `ORDER BY total_peliculas DESC LIMIT 5`

---

## 3) Follow-up refinement

Secuencia:

1) `dame las 5 peliculas mas vistas`  
2) `ahora solo las de 2006`

Evidencia observada (resumen real):

- El follow-up agrega filtro `WHERE f.release_year = 2006`
- Mantiene ranking por rentals y `LIMIT 5`
- Devuelve 5 filas filtradas al anio 2006

---

## 4) Comandos rapidos para ejecutar todo seguido

```bash
# Q1
curl -sS http://localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"tp-multiagentes","messages":[{"role":"user","content":"cuantas peliculas hay en total?"}]}'

# Q2
curl -sS http://localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"tp-multiagentes","messages":[{"role":"user","content":"dame las 5 peliculas mas vistas"}]}'

# Q3
curl -sS http://localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"tp-multiagentes","messages":[{"role":"user","content":"top 5 actores con mas peliculas"}]}'

# Follow-up
curl -sS http://localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"tp-multiagentes","messages":[{"role":"user","content":"ahora solo las de 2006"}]}'
```

---

## 5) Evidencia de ejecucion (captura de esta corrida)

Fecha de corrida: 2026-04-20.

- `docker compose ps` con `app` y `db` en `healthy`.
- `schema-agent/answer` devolvio `status: ready` y persistio `answers.q_demo`.
- Q1 devolvio `total_movies = 1000`.
- Q2 devolvio top peliculas por rentals (ej: `Bucket Brotherhood` 34).
- Q3 devolvio top actores por cantidad de peliculas.
- Follow-up aplico filtro de anio 2006 y devolvio 5 filas.

Con esto queda una demo reproducible y verificable sobre el dataset DVD Rental.
