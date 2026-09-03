#!/usr/bin/env bash
# Knowledge + phase/risk backup every 6h (cron: 0 */6 * * * bash /srv/capitalizator/app/infra/deploy/backup.sh)
set -euo pipefail
DATA=/srv/capitalizator
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
docker compose -f "$DATA/app/infra/deploy/compose.yml" run --rm -T desk \
  python -m capitalizator.ops.backup pack --userdir /data --dest "/data/../backups/knowledge-$STAMP" --no-tape \
  || echo "backup pack failed at $STAMP" >&2
find "$DATA/backups" -maxdepth 1 -name 'knowledge-*' -mtime +14 -exec rm -rf {} +
