#!/usr/bin/env bash
# GhostWorktree demo: full lifecycle on a throwaway repo.
# Steps: create -> list -> status -> dirty cleanup refusal -> cleanup --force.
# The demo repo's real .env carries a planted marker; it must appear
# nowhere in the worktree or registry (env is seeded from .env.example only).
set -u

DEMO_ROOT="$(mktemp -d /tmp/ghostworktree-demo.XXXXXX)"
REPO="$DEMO_ROOT/repo"
MARKER="planted-marker-not-a-real-secret"
echo "Demo root: $DEMO_ROOT"

# How to invoke the CLI: $GHOSTWORKTREE_CMD, else the console script,
# else the module form from this checkout.
if [ -n "${GHOSTWORKTREE_CMD:-}" ]; then
  GW=($GHOSTWORKTREE_CMD)
elif command -v ghostworktree >/dev/null 2>&1; then
  GW=(ghostworktree)
else
  GW=(env "PYTHONPATH=$(cd "$(dirname "$0")/.." && pwd)/src" python3 -m ghostworktree)
fi
echo "CLI: ${GW[*]}"

# A tiny demo repo to manage worktrees for.
git init -q "$REPO"
git -C "$REPO" config user.email "demo@example.com"
git -C "$REPO" config user.name "GhostWorktree Demo"
printf '"""Demo app."""\n' > "$REPO/app.py"
printf 'APP_NAME=demo\nFAKE_TOKEN=%s\nPORT=0\n' "$MARKER" > "$REPO/.env"
printf 'APP_NAME=\nFAKE_TOKEN=\nPORT=\n' > "$REPO/.env.example"
printf '.env\n' > "$REPO/.gitignore"
git -C "$REPO" add app.py .env.example .gitignore
git -C "$REPO" commit -qm "base"

echo
echo "== create =="
"${GW[@]}" create "$REPO" demo-task || exit 1

echo
echo "== list =="
"${GW[@]}" list "$REPO" || exit 1

echo
echo "== status =="
"${GW[@]}" status "$REPO" demo-task || exit 1

WT="$(git -C "$REPO" worktree list --porcelain | awk '/^worktree /{print $2}' | grep -v "^$REPO\$" | head -n 1)"
echo "Worktree: $WT"

echo
echo "== env rule: the planted real-.env marker must appear nowhere =="
if grep -r "$MARKER" "$WT" "$(dirname "$REPO")/$(basename "$REPO")-worktrees/registry.json" >/dev/null 2>&1; then
  echo "FAIL: real .env marker leaked into the worktree or registry"
  exit 1
else
  echo "OK: marker absent; worktree .env was seeded from .env.example only"
fi

echo
echo "== dirty the worktree, then cleanup (must refuse) =="
printf 'uncommitted agent work\n' >> "$WT/app.py"
if "${GW[@]}" cleanup "$REPO" demo-task; then
  echo "UNEXPECTED: cleanup removed a dirty worktree without --force"
  exit 1
else
  echo "OK: cleanup refused the dirty worktree by default"
fi

echo
echo "== cleanup --force =="
"${GW[@]}" cleanup "$REPO" demo-task --force || exit 1
git -C "$REPO" worktree list

echo
echo "Demo done. Throwaway root kept for inspection: $DEMO_ROOT"
