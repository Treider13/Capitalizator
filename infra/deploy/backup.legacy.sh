#!/usr/bin/env bash
# Knowledge + phase/risk backup every 6h. cron (user trader):
#   0 */6 * * * bash /srv/capitalizator/app/infra/deploy/backup.sh
set -euo pipefail
DATA=/srv/capitalizator
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
export CAP_DATA="$DATA/userdir" CAP_UID="$(id -u)" CAP_GID="$(id -g)"
cd "$DATA/app/infra/deploy"
# --no-deps: do not re-run `init`; the backups dir is mounted explicitly (audit A6: the
# old --dest resolved inside the throw-away container).
docker compose -f compose.legacy.yml run --rm --no-deps -T -v "$DATA/backups:/backups" desk \
  python -m capitalizator.ops.backup pack --userdir /data --dest "/backups/knowledge-$STAMP" --no-tape \
  || { echo "backup pack failed at $STAMP" >&2; exit 1; }
find "$DATA/backups" -maxdepth 1 -name 'knowledge-*' -mtime +14 -exec rm -rf {} +
echo "backup ok: $DATA/backups/knowledge-$STAMP"
