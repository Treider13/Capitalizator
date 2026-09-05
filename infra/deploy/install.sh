#!/usr/bin/env bash
# Idempotent VPS bootstrap (Ubuntu 24.04/26.04). Run as root ONCE, re-running is safe.
#   bash install.sh <ssh-public-key> [allow-from-ip]
# Creates user `trader`, hardens SSH (keys only, no root), UFW (22 only, optionally from one IP),
# fail2ban, UTC + Bybit clock (not chrony), Docker, the data directory, and clones/updates the repo.
set -euo pipefail
PUBKEY="${1:-}"; ALLOW_FROM="${2:-}"
REPO="${CAP_REPO:-https://github.com/Treider13/Capitalizator.git}"
BRANCH="${CAP_BRANCH:-main}"
DATA=/srv/capitalizator
log(){ printf '\n== %s\n' "$*"; }

log "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ufw fail2ban chrony unattended-upgrades git ca-certificates curl gnupg >/dev/null

log "time: UTC (chrony off — hypervisor NTP can sit ~70s off Bybit → 10002)"
timedatectl set-timezone UTC
systemctl disable --now chrony >/dev/null 2>&1 || true
systemctl disable --now systemd-timesyncd >/dev/null 2>&1 || true

log "user trader"
id trader >/dev/null 2>&1 || adduser --disabled-password --gecos "" trader
usermod -aG sudo trader
install -d -m 700 -o trader -g trader /home/trader/.ssh
if [ -n "$PUBKEY" ]; then
  grep -qxF "$PUBKEY" /home/trader/.ssh/authorized_keys 2>/dev/null || echo "$PUBKEY" >> /home/trader/.ssh/authorized_keys
fi
chmod 600 /home/trader/.ssh/authorized_keys 2>/dev/null || true
chown -R trader:trader /home/trader/.ssh
rm -f /etc/sudoers.d/trader  # no passwordless root for the service user (audit F); docker group is enough to deploy

log "docker"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null || apt-get install -y -qq docker.io docker-compose-v2 >/dev/null
fi
systemctl enable --now docker >/dev/null
usermod -aG docker trader

log "data directory"
install -d -m 750 -o trader -g trader "$DATA" "$DATA/userdir" "$DATA/backups" "$DATA/logs"
install -d -m 700 -o trader -g trader "$DATA/userdir/secrets"

log "repo"
if [ -d "$DATA/app/.git" ]; then
  sudo -u trader git -C "$DATA/app" fetch -q origin && sudo -u trader git -C "$DATA/app" checkout -q "$BRANCH" && sudo -u trader git -C "$DATA/app" pull -q --ff-only origin "$BRANCH"
elif [ -f "$DATA/app/pyproject.toml" ]; then
  echo "code already unpacked at $DATA/app (no .git — uploaded tree; deploy.sh will not git pull)"
  chown -R trader:trader "$DATA/app"
else
  sudo -u trader git clone -q --branch "$BRANCH" "$REPO" "$DATA/app" \
    || { echo "clone failed (private repo?). Upload the tree to $DATA/app or add a deploy key, then re-run."; exit 1; }
fi

log "Bybit clock at boot + every 10 min"
if [ -f "$DATA/app/infra/deploy/sync-bybit-clock.sh" ]; then
  install -m 755 "$DATA/app/infra/deploy/sync-bybit-clock.sh" /usr/local/sbin/sync-bybit-clock.sh
  install -m 644 "$DATA/app/infra/deploy/bybit-clock.service" /etc/systemd/system/bybit-clock.service
  install -m 644 "$DATA/app/infra/deploy/bybit-clock.timer" /etc/systemd/system/bybit-clock.timer
  systemctl daemon-reload
  systemctl enable --now bybit-clock.timer >/dev/null
  /usr/local/sbin/sync-bybit-clock.sh || true
fi

log "operator SSH keys from the repo"
KEYS_DIR="$DATA/app/infra/deploy/operator_keys"
if [ -d "$KEYS_DIR" ]; then
  shopt -s nullglob
  for f in "$KEYS_DIR"/*.pub; do
    key="$(tr -d '\r' < "$f" | head -n1)"
    [ -n "$key" ] || continue
    grep -qxF "$key" /home/trader/.ssh/authorized_keys 2>/dev/null || echo "$key" >> /home/trader/.ssh/authorized_keys
  done
  shopt -u nullglob
  chmod 600 /home/trader/.ssh/authorized_keys
  chown -R trader:trader /home/trader/.ssh
fi

log "firewall"
ufw --force default deny incoming >/dev/null
ufw --force default allow outgoing >/dev/null
if [ -n "$ALLOW_FROM" ]; then ufw allow from "$ALLOW_FROM" to any port 22 proto tcp >/dev/null; else ufw allow 22/tcp >/dev/null; fi
ufw --force enable >/dev/null

log "fail2ban"
cat > /etc/fail2ban/jail.d/sshd.local <<'J'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
J
systemctl enable --now fail2ban >/dev/null && systemctl restart fail2ban

log "sshd hardening (only with CAP_HARDEN=1 and a key present — never lock yourself out)"
if [ "${CAP_HARDEN:-0}" = "1" ] && [ -s /home/trader/.ssh/authorized_keys ]; then
  install -d /etc/ssh/sshd_config.d
  cat > /etc/ssh/sshd_config.d/99-capitalizator.conf <<'S'
PasswordAuthentication no
PermitRootLogin no
KbdInteractiveAuthentication no
S
  sshd -t && systemctl reload ssh
  echo "password login disabled; use: ssh trader@<vps>"
else
  echo "password login left ON. After 'ssh trader@<vps>' works with your key: CAP_HARDEN=1 bash install.sh"
fi

log "unattended upgrades (no automatic reboot)"
cat > /etc/apt/apt.conf.d/52capitalizator <<'U'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Package-Blacklist { "docker-ce"; "docker-ce-cli"; "containerd.io"; "docker.io"; };
U

log "done. Next: sudo -u trader bash $DATA/app/infra/deploy/deploy.sh"
