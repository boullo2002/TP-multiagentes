#!/usr/bin/env bash
set -euo pipefail

ZIP_PATH="/db-data/dvdrental.zip"

if [[ ! -f "$ZIP_PATH" ]]; then
  echo "No se encontró $ZIP_PATH. Asegurate de tener db-data/dvdrental.zip en el repo."
  exit 1
fi

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

echo "Extrayendo DVD Rental desde $ZIP_PATH ..."
unzip -q "$ZIP_PATH" -d "$TMP_DIR"

TAR_FILE="$(find "$TMP_DIR" -maxdepth 3 -type f -name "*.tar" | head -n 1 || true)"
SQL_FILE="$(find "$TMP_DIR" -maxdepth 3 -type f -name "*.sql" | head -n 1 || true)"

if [[ -n "$TAR_FILE" ]]; then
  echo "Restaurando desde tar: $TAR_FILE"
  pg_restore --no-owner --no-privileges --verbose -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$TAR_FILE"
  echo "Restore completo."
  exit 0
fi

if [[ -n "$SQL_FILE" ]]; then
  echo "Restaurando desde sql: $SQL_FILE"
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$SQL_FILE"
  echo "Restore completo."
  exit 0
fi

echo "No se encontró .tar ni .sql dentro de dvdrental.zip. Contenido:"
find "$TMP_DIR" -maxdepth 3 -type f | sed -n '1,200p'
exit 1

