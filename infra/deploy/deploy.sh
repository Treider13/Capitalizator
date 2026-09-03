#!/usr/bin/env bash
# Build/update and (re)start the stack. Idempotent. Run as `trader`.
#   bash deploy.sh            # pull current branch, build, up
#   CAP_BRANCH=main bash deploy.sh
set -euo pipefail
DATA=/srv/capitalizator
APP="$DATA/app"
cd "$APP"
if [ -d .git ]; then
  BRANCH="${CAP_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
  git fetch -q origin && git checkout -q "$BRANCH" && git pull -q --ff-only origin "$BRANCH"
else
  echo "no .git in $APP: deploying the uploaded tree as is"
fi
cd infra/deploy
[ -f .env ] || { cp ../../.env.example .env; chmod 600 .env; echo "created infra/deploy/.env from .env.example — fill BYBIT_* (or use /data/secrets/bybit.json)"; }
export CAP_DATA="$DATA/userdir"
docker compose build --pull
docker compose up -d --remove-orphans
docker compose ps
echo "console: ssh -L 8082:127.0.0.1:8082 trader@<vps>  →  http://127.0.0.1:8082"
