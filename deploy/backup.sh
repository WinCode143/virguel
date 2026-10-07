#!/bin/sh
# Backup diario de la base y de las fotos. Programar con cron, por ejemplo:
#   30 2 * * * /opt/virguel/deploy/backup.sh /opt/backups
set -e
DESTINO=${1:-./backups}
FECHA=$(date +%Y%m%d)
mkdir -p "$DESTINO"
cd "$(dirname "$0")"
docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$DESTINO/virguel_$FECHA.sql.gz"
docker compose -f docker-compose.prod.yml run --rm -T -v "$DESTINO":/backup web tar czf "/backup/media_$FECHA.tgz" -C /app media
find "$DESTINO" -name 'virguel_*' -mtime +30 -delete
find "$DESTINO" -name 'media_*' -mtime +30 -delete
