#!/usr/bin/env bash
# Build a release, atomically switch the `current` symlink, restart the service,
# and revert if the new build fails its health check.
#
# DRAFT: the paths/user/service below are placeholders. Final values come from
# the Ansible release-dir layout (Phase 2). Invoked by poll.sh with the target
# SHA as $1.
set -euo pipefail

# --- config (overridable via env / Ansible template) ------------------------
REPO_DIR="${REPO_DIR:-/srv/confessio-front/repo}"
RELEASES_DIR="${RELEASES_DIR:-/srv/confessio-front/releases}"
CURRENT_LINK="${CURRENT_LINK:-/srv/confessio-front/current}"
STATE_DIR="${STATE_DIR:-/srv/confessio-front/state}"
ENV_FILE="${ENV_FILE:-/srv/confessio-front/.env}"
SERVICE_NAME="${SERVICE_NAME:-confessio-front}"
APP_PORT="${APP_PORT:-3000}"
KEEP_RELEASES="${KEEP_RELEASES:-3}"
HEALTH_RETRIES="${HEALTH_RETRIES:-15}"
HEALTH_DELAY="${HEALTH_DELAY:-2}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

SHA="${1:?usage: deploy.sh <git-sha>}"
RELEASE_DIR="$RELEASES_DIR/$SHA"

notify() {
  echo "$1"
  [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ] || return 0
  curl -fsS -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" >/dev/null || true
}

fail() {
  notify "❌ confessio-front deploy ${SHA:0:8} failed: $1"
  exit 1
}
trap 'fail "unexpected error on line $LINENO"' ERR

# Health check: poll /api/health for 200 and confirm the served version matches
# what we just built (so a stale process serving the old bundle is caught).
health_ok() {
  local expected="$1" body
  for _ in $(seq "$HEALTH_RETRIES"); do
    if body="$(curl -fsS "http://127.0.0.1:${APP_PORT}/api/health")"; then
      case "$body" in *"\"version\":\"$expected\""*) return 0 ;; esac
    fi
    sleep "$HEALTH_DELAY"
  done
  return 1
}

# --- build ------------------------------------------------------------------
git -C "$REPO_DIR" fetch --quiet origin
mkdir -p "$RELEASE_DIR"
git -C "$REPO_DIR" archive "$SHA" | tar -x -C "$RELEASE_DIR"

# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a   # NEXT_PUBLIC_* must be present at BUILD time

cd "$RELEASE_DIR"
corepack enable
pnpm install --frozen-lockfile
pnpm build

version="$(node -p "require('./package.json').version")"

# --- atomic switch + health gate -------------------------------------------
previous="$(readlink "$CURRENT_LINK" 2>/dev/null || true)"
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
sudo systemctl restart "$SERVICE_NAME"

if ! health_ok "$version"; then
  if [ -n "$previous" ]; then
    ln -sfn "$previous" "$CURRENT_LINK"
    sudo systemctl restart "$SERVICE_NAME"
    fail "health check failed — reverted to $(basename "$previous")"
  fi
  fail "health check failed — no previous release to revert to"
fi

# --- record + prune ---------------------------------------------------------
mkdir -p "$STATE_DIR"
echo "$SHA" > "$STATE_DIR/last-deployed-sha"

ls -1dt "$RELEASES_DIR"/*/ 2>/dev/null | tail -n "+$((KEEP_RELEASES + 1))" \
  | xargs -r rm -rf

trap - ERR
notify "✅ confessio-front deployed v${version} (${SHA:0:8})"
