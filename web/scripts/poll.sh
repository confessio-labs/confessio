#!/usr/bin/env bash
# Pull-based deploy trigger. Run on a 60s systemd timer (unit lives in Ansible).
# Compares main's remote HEAD to the last deployed SHA and, if changed, runs the
# deploy under a non-blocking lock so overlapping ticks don't race.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/srv/confessio-front/repo}"
STATE_DIR="${STATE_DIR:-/srv/confessio-front/state}"
LOCK_FILE="${LOCK_FILE:-/run/confessio-front-deploy.lock}"
BRANCH="${BRANCH:-main}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

remote="$(git -C "$REPO_DIR" ls-remote origin "refs/heads/$BRANCH" | cut -f1)"
[ -n "$remote" ] || { echo "could not resolve remote HEAD" >&2; exit 1; }

last="$(cat "$STATE_DIR/last-deployed-sha" 2>/dev/null || true)"
[ "$remote" = "$last" ] && exit 0

exec flock -n "$LOCK_FILE" "$DIR/deploy.sh" "$remote"
