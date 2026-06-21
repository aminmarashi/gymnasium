#!/usr/bin/env bash
#
# Reset the Cloudflare tunnel by deleting the old tunnel + DNS route and
# recreating them. Use this when switching machines or when you hit Error
# 1033 because the CNAME record points at a stale tunnel UUID.
#
# Env overrides (same as start.sh, .env is auto-loaded):
#   DOMAIN        default marashi.ai
#   TUNNEL_NAME   default gymnasium
#   APP_HOST      default gymnasium.marashi.ai

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
# Same .env auto-load as start.sh so a single config drives both.
if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${ROOT}/.env"
  set +a
fi

DOMAIN="${DOMAIN:-marashi.ai}"
TUNNEL_NAME="${TUNNEL_NAME:-gymnasium}"
APP_HOST="${APP_HOST:-gymnasium.$DOMAIN}"

command -v cloudflared >/dev/null || { echo "cloudflared not on PATH" >&2; exit 1; }

if [ ! -f "${HOME}/.cloudflared/cert.pem" ]; then
  echo "cloudflared is not logged in. Run:" >&2
  echo "  cloudflared tunnel login" >&2
  exit 1
fi

echo "==> Deleting tunnel '${TUNNEL_NAME}'..."
cloudflared tunnel delete "$TUNNEL_NAME" 2>/dev/null && \
  echo "    deleted." || \
  echo "    tunnel did not exist or was already deleted."

echo "==> Creating tunnel '${TUNNEL_NAME}'..."
cloudflared tunnel create "$TUNNEL_NAME"

echo "==> Adding DNS route (overwriting stale record)..."
if cloudflared tunnel route dns -f "$TUNNEL_NAME" "$APP_HOST" 2>&1; then
  echo "    routed: $APP_HOST"
  echo ""
  echo "Done. You can now run ./start.sh"
else
  echo "    FAILED to route $APP_HOST"
  echo ""
  echo "The DNS route could not be created automatically."
  echo "This usually means an A or AAAA record exists that cloudflared cannot overwrite."
  echo ""
  echo "To fix, go to the Cloudflare dashboard:"
  echo "  1. Open https://dash.cloudflare.com -> ${DOMAIN} -> DNS -> Records"
  echo "  2. Delete the A/AAAA record(s) for: ${APP_HOST}"
  echo "  3. Re-run: ./reset-tunnel.sh"
  echo "     (or manually: cloudflared tunnel route dns -f ${TUNNEL_NAME} ${APP_HOST})"
  exit 1
fi
