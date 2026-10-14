#!/usr/bin/env bash
# Rebuild the registry, run every test, check the repository, and write the demonstration packs.
# Run from anywhere; the script finds the repository root itself. Needs the project environment (.venv).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY=".venv/bin/python"
REPORTS="agent-context/reports"
echo "== build"
$PY agent-context/ctx.py build > /dev/null && echo "registry rebuilt"
echo "== tests"
$PY -m unittest discover -s agent-context/tests
echo "== check"
if $PY agent-context/ctx.py check > "$REPORTS/check_summary.json"; then
  echo "no stale inputs or packs; written to $REPORTS/check_summary.json"
else
  echo "STALE items found; see $REPORTS/check_summary.json"
fi
echo "== demo"
$PY agent-context/ctx.py demo > "$REPORTS/demo_summary.json" && echo "written to $REPORTS/demo_summary.json"
