#!/usr/bin/env bash
# Synchronize the InterClarify checkout from the GitHub main branch.
#
# The server uses this script as the only source-code transfer path.  It does
# not copy files from the developer machine and refuses to overwrite a dirty
# server checkout.
set -euo pipefail

REPO_ROOT="${INTERCLARIFY_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/InterClarify}"
GIT_URL="${INTERCLARIFY_GIT_URL:-https://github.com/Vitalrubbish/InterClarify.git}"
GIT_REF="${INTERCLARIFY_GIT_REF:-main}"

echo "[sync_from_github] repo=$REPO_ROOT ref=$GIT_REF"

if [[ -e "$REPO_ROOT" && ! -d "$REPO_ROOT/.git" ]]; then
  echo "[sync_from_github] target exists but is not a git checkout: $REPO_ROOT" >&2
  exit 2
fi

if [[ ! -d "$REPO_ROOT/.git" ]]; then
  mkdir -p "$(dirname "$REPO_ROOT")"
  git clone --branch "$GIT_REF" --single-branch "$GIT_URL" "$REPO_ROOT"
else
  if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    echo "[sync_from_github] refusing to update a dirty checkout: $REPO_ROOT" >&2
    exit 3
  fi

  CURRENT_URL="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"
  if [[ "$CURRENT_URL" != "$GIT_URL" ]]; then
    git -C "$REPO_ROOT" remote set-url origin "$GIT_URL"
  fi

  git -C "$REPO_ROOT" fetch --prune origin "$GIT_REF"

  CURRENT_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
  if [[ "$CURRENT_BRANCH" != "$GIT_REF" ]]; then
    if git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/$GIT_REF"; then
      git -C "$REPO_ROOT" switch "$GIT_REF"
    else
      git -C "$REPO_ROOT" switch --track "origin/$GIT_REF"
    fi
  fi
  git -C "$REPO_ROOT" pull --ff-only origin "$GIT_REF"
fi

echo "[sync_from_github] commit=$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" status --short --branch
