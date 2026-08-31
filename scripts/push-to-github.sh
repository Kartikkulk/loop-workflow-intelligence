#!/usr/bin/env bash
#
# Creates the private repo under the right account and pushes.
#
# Run AFTER `gh auth login` has completed as Kartikkulk. Refuses to run against
# the wrong account, because three similarly-named accounts are authenticated on
# this machine and pushing to the wrong one is tedious to undo.
#
#   ./scripts/push-to-github.sh [repo-name]
#
set -euo pipefail

WANT_OWNER="Kartikkulk"
REPO="${1:-loop-workflow-intelligence}"

cd "$(dirname "$0")/.."

echo "==> checking the active account"
ACTIVE="$(gh api user --jq .login 2>/dev/null || true)"
if [[ -z "$ACTIVE" ]]; then
  echo "    gh is not authenticated. Run this first, on its own, and let it finish:"
  echo "      gh auth login --hostname github.com --web"
  exit 1
fi
if [[ "$ACTIVE" != "$WANT_OWNER" ]]; then
  echo "    active account is '$ACTIVE', not '$WANT_OWNER'."
  echo ""
  echo "    Authenticated accounts:"
  gh auth status 2>&1 | grep -E "Logged in to" | sed 's/^/      /'
  echo ""
  echo "    If $WANT_OWNER is listed:   gh auth switch --user $WANT_OWNER"
  echo "    If it is not:               gh auth login --hostname github.com --web"
  exit 1
fi
echo "    ok — $ACTIVE"

echo "==> checking the working tree"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "    uncommitted changes present. Commit or stash them first:"
  git status --short | sed 's/^/      /'
  exit 1
fi
echo "    clean · $(git rev-list --count HEAD) commit(s) on $(git rev-parse --abbrev-ref HEAD)"

if gh repo view "$WANT_OWNER/$REPO" >/dev/null 2>&1; then
  echo "==> repo $WANT_OWNER/$REPO already exists — adding it as a remote"
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/$WANT_OWNER/$REPO.git"
  git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
else
  echo "==> creating private repo $WANT_OWNER/$REPO and pushing"
  gh repo create "$WANT_OWNER/$REPO" \
    --private \
    --source=. \
    --remote=origin \
    --push \
    --description "AI-powered workflow intelligence: detects repetitive enterprise workflows, converts them into automations, and earns the right to run them through a measured trust ladder."
fi

echo "==> verifying"
gh repo view "$WANT_OWNER/$REPO" --json name,visibility,url,defaultBranchRef \
  --template '    {{.name}} · {{.visibility}} · default {{.defaultBranchRef.name}}{{"\n"}}    {{.url}}{{"\n"}}'

echo ""
echo "Next:"
echo "  ./scripts/bootstrap-github.sh <backend-handle> <frontend-handle>"
echo "    creates labels, the 'Submission 4 Sep' milestone, invites both devs,"
echo "    and files the 10 opening issues pre-assigned."
