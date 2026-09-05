#!/bin/bash
# Set the OS clock from Bybit /v5/market/time. Public, unsigned.
# Host NTP (chrony) on some VPS hypervisors stays ~70s off the venue;
# Bybit then rejects signed calls with 10002 (recv_window ~5s).
set -euo pipefail
raw="$(curl -fsS --max-time 10 https://api.bybit.com/v5/market/time)"
sec="$(python3 -c 'import json,sys; print(int(json.load(sys.stdin)["result"]["timeSecond"]))' <<<"$raw")"
if [ "$sec" -lt 1700000000 ] || [ "$sec" -gt 4102444800 ]; then
  echo "unreasonable bybit timeSecond=$sec" >&2
  exit 1
fi
date -u -s "@$sec" >/dev/null
echo "synced to bybit timeSecond=$sec"
