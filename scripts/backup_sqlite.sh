#!/usr/bin/env bash
# Backup diário do SQLite com rotação de 14 dias
set -euo pipefail

DB_PATH="${SQLITE_PATH:-/data/resusbot.db}"
BACKUP_DIR="${BACKUP_DIR:-/data/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +"%Y%m%d-%H%M")
DEST="$BACKUP_DIR/resusbot-$TIMESTAMP.db"

if [ ! -f "$DB_PATH" ]; then
    echo "[backup] DB não encontrado: $DB_PATH"
    exit 1
fi

sqlite3 "$DB_PATH" ".backup '$DEST'"
echo "[backup] Salvo: $DEST ($(du -sh "$DEST" | cut -f1))"

# Rotação
find "$BACKUP_DIR" -name "resusbot-*.db" -mtime +$RETENTION_DAYS -delete
echo "[backup] Rotação: mantidos últimos $RETENTION_DAYS dias"
