#!/usr/bin/env bash
#
# Creates labels, a milestone and the opening issues, and invites the team.
# Run once, after the repo exists and `gh` is authenticated as its owner.
#
#   ./scripts/bootstrap-github.sh <backend-github-handle> <frontend-github-handle>
#
set -euo pipefail

BACKEND="${1:?usage: bootstrap-github.sh <backend-handle> <frontend-handle>}"
FRONTEND="${2:?usage: bootstrap-github.sh <backend-handle> <frontend-handle>}"
DUE="2026-09-04T23:59:59Z"

echo "==> labels"
add_label() {
  gh label create "$1" --color "$2" --description "$3" --force >/dev/null
  echo "    $1"
}
add_label "area:api"        "1d76db" "Backend - apps/api/"
add_label "area:web"        "0e8a16" "Frontend - apps/web/"
add_label "area:collector"  "5319e7" "Browser collector"
add_label "area:docs"       "c5def5" "Docs, demo, artefact"
add_label "api-contract"    "d93f0b" "Crosses the API boundary - needs contract + fixtures"
add_label "blocker"         "b60205" "Blocks the submission"
add_label "cut-candidate"   "fbca04" "First to drop if time runs short"

echo "==> milestone"
gh api "repos/{owner}/{repo}/milestones" -f title="Submission 4 Sep" \
  -f due_on="$DUE" \
  -f description="Hackathon submission. Feature freeze Thursday 12:00." >/dev/null 2>&1 \
  || echo "    (already exists)"

echo "==> collaborators"
for handle in "$BACKEND" "$FRONTEND"; do
  gh api -X PUT "repos/{owner}/{repo}/collaborators/$handle" -f permission=push >/dev/null
  echo "    invited $handle (push)"
done

echo "==> issues"
new_issue() {
  gh issue create --title "$1" --body "$2" --label "$3" --assignee "$4" \
    --milestone "Submission 4 Sep" | sed 's|^|    |'
}

new_issue "Live Microsoft Graph ingestion adapter" \
"Everything execution-side is mocked. One real read-only source changes \"could this touch production?\" from an argument into a demo.

Land it as an **ingestion adapter**, not an execution connector - lower risk, and it feeds the Observation screen.

- \`/me/messages/delta\` needs only delegated consent, no tenant admin
- Emit canonical events through the same path as the browser collector
- Register as a source of kind \`api_connector\`, so consent/pause/revoke work unchanged

**Acceptance:** a real mailbox produces canonical events visible on /sources, and detection runs over them.

Highest-value item on the list. See collectors/README.md for the API surfaces." \
"area:api" "$BACKEND"

new_issue "Verify the Postgres path from a clean clone" \
"\`docker compose up --build\` is the least-tested route in the repo, and it is what a judge is most likely to actually run.

**Acceptance:** from a fresh clone, \`docker compose up --build\` brings up Postgres + API + console, seeded, with the console showing detected workflows." \
"area:api,blocker" "$BACKEND"

new_issue "Persist replay failures so ROI can trend failure modes" \
"Replay failures are returned but not stored, so /analytics/roi cannot show whether failure modes are shrinking over time - the chart that makes the system look alive.

**Acceptance:** ROI shows a failure-mode trend across repeated replays." \
"area:api,cut-candidate" "$BACKEND"

new_issue "Loading skeletons on all six screens" \
"Every screen currently flashes a text spinner and then shifts layout when data lands.

**Acceptance:** skeletons match the real layout; no layout shift when data arrives. Verify with \`make web-mock\` - fixtures inject 180ms latency deliberately." \
"area:web" "$FRONTEND"

new_issue "Empty states that teach the next action" \
"/automations and /exceptions with zero rows say \"nothing here\". They should say what to do next.

**Acceptance:** every empty state names the action that fills it, and links to the screen where you take it." \
"area:web" "$FRONTEND"

new_issue "Responsive pass down to 1024px" \
"The console is desktop-only. Below ~1100px the stat grids and the flow-definition table break.

**Acceptance:** usable at 1024px with no horizontal page scroll. Wide tables scroll inside their own container, not the page." \
"area:web,cut-candidate" "$FRONTEND"

new_issue "Keyboard and focus pass" \
"A judge may drive this by keyboard. The trust ladder, the promote button and the exception queue are the likely paths.

**Acceptance:** every interactive control reachable by Tab with a visible focus ring; expandable shadow-run rows operable by keyboard." \
"area:web" "$FRONTEND"

new_issue "Install the extension manually and confirm it reports" \
"The one thing never verified in a loaded-extension environment: Chrome 137+ removed \`--load-extension\`, so it could not be automated. Both shipped files are tested directly and the collector API is tested end to end, but Chrome's own plumbing is unverified.

Do this on day one, not day four.

**Acceptance:** extension loaded unpacked in real Chrome, token pasted, events visible on /sources within a minute of browsing." \
"area:collector,blocker" "@me"

new_issue "README screenshots" \
"Placeholders today. Needs Discovery, the trust ladder mid-climb, and Observation.

**Acceptance:** three screenshots committed and referenced from README.md." \
"area:docs" "@me"

new_issue "Rehearse DEMO.md three times and time it" \
"Once Tuesday, once Wednesday after fixes, once Thursday with all three people driving.

**Acceptance:** the five-minute script runs in five minutes, and \`make demo\` reliably returns to the exact starting state." \
"area:docs,blocker" "@me"

echo ""
echo "Done. Next: gh issue list --milestone 'Submission 4 Sep'"
