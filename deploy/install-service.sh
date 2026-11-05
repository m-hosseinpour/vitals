#!/usr/bin/env bash
# Install or refresh the per-user systemd unit and start the dashboard.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/vitals.service"

if [[ ! -x "$ROOT/.venv/bin/uvicorn" ]]; then
  echo "Run 'uv sync' in $ROOT first." >&2
  exit 1
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Create $ROOT/.env from .env.example first." >&2
  exit 1
fi

mkdir -p "$UNIT_DIR"
sed "s|@ROOT@|$ROOT|g" "$ROOT/deploy/vitals.service.in" > "$UNIT"
chmod 644 "$UNIT"

systemctl --user daemon-reload
systemctl --user enable --now vitals.service
systemctl --user --no-pager --full status vitals.service

echo
echo "Listening on 127.0.0.1:8010. Add deploy/Caddyfile to /etc/caddy/Caddyfile"
echo "and make sure vitals.m-hosseinpour.ir resolves to this server."
