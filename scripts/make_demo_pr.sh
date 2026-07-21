#!/usr/bin/env bash
# Create a small PUBLIC GitHub repo with one verifiable PR, so Lever's
# "paste a PR URL" flow has a reliable, real target for demos.
#
# Requirements:
#   - A GitHub token with permission to CREATE repos:
#       * classic PAT with the `repo` scope, OR
#       * fine-grained PAT (All repos) with Administration: read/write + Contents: read/write + Pull requests: read/write
#     Pass it as GH_DEMO_TOKEN (NOT the read-only LEVER token in .env).
#   - git and curl.
#
# Usage:
#   GH_DEMO_TOKEN=ghp_xxx ./scripts/make_demo_pr.sh [repo-name]
#
# Prints the created pull request URL on success. Paste that into Lever.

set -euo pipefail

REPO_NAME="${1:-lever-demo-ratelimiter}"
TOKEN="${GH_DEMO_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: set GH_DEMO_TOKEN to a GitHub token that can create repos (classic 'repo' scope)." >&2
  exit 1
fi

api() {
  # api METHOD PATH [JSON_BODY]
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sS -X "$method" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com${path}" -d "$body"
  else
    curl -sS -X "$method" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com${path}"
  fi
}

echo "Resolving token owner…"
LOGIN="$(api GET /user | python3 -c 'import sys,json;print(json.load(sys.stdin)["login"])')"
echo "  owner: $LOGIN"

echo "Creating public repo $LOGIN/$REPO_NAME…"
api POST /user/repos "{\"name\":\"$REPO_NAME\",\"private\":false,\"auto_init\":false,\"description\":\"Lever demo: a small verifiable rate-limiter change.\"}" >/dev/null || true

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

REMOTE="https://x-access-token:${TOKEN}@github.com/${LOGIN}/${REPO_NAME}.git"

# --- base version (main): fixed-window limiter ---
cat > rate_limiter.py <<'PY'
"""Fixed-window rate limiter — the 'old' version."""
import time


class RateLimiter:
    def __init__(self, limit_per_sec: int):
        self.limit = limit_per_sec
        self.window_start = time.time()
        self.count = 0

    def admit(self, tenant_id: str, now: float) -> bool:
        if now - self.window_start >= 1.0:
            self.window_start = now
            self.count = 0
        if self.count < self.limit:
            self.count += 1
            return True
        return False
PY

git init -q
git checkout -q -b main
git add rate_limiter.py
git -c user.email="demo@lever.dev" -c user.name="Lever Demo" commit -q -m "Fixed-window rate limiter"
git remote add origin "$REMOTE"
git push -q -u origin main

# --- head version (branch): sliding window + burst allowance ---
git checkout -q -b per-tenant-burst
cat > rate_limiter.py <<'PY'
"""Sliding-window rate limiter with a per-tenant burst allowance — the 'new' version."""
import time
from collections import deque, defaultdict


class RateLimiter:
    def __init__(self, limit_per_sec: int, burst: int = 0):
        self.limit = limit_per_sec
        self.burst = burst
        self.windows = defaultdict(deque)
        self.burst_used = 0

    def admit(self, tenant_id: str, now: float) -> bool:
        w = self.windows[tenant_id]
        while w and now - w[0] >= 1.0:
            w.popleft()
        if len(w) < self.limit:
            w.append(now)
            return True
        if self.burst_used < self.burst:
            self.burst_used += 1
            w.append(now)
            return True
        return False
PY

git add rate_limiter.py
git -c user.email="demo@lever.dev" -c user.name="Lever Demo" commit -q -m "Switch to sliding window with burst allowance"
git push -q -u origin per-tenant-burst

echo "Opening pull request…"
PR_URL="$(api POST "/repos/${LOGIN}/${REPO_NAME}/pulls" \
  "{\"title\":\"Sliding window with burst allowance\",\"head\":\"per-tenant-burst\",\"base\":\"main\",\"body\":\"Old: fixed window. New: sliding window + burst.\"}" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("html_url") or d)')"

echo
echo "Demo PR ready. Paste this into Lever:"
echo "  $PR_URL"
