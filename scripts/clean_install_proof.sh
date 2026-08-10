#!/usr/bin/env bash
# The clean-venv proof — wayfinder ticket 06, framework-packaging §3.6.
#
#   scripts/clean_install_proof.sh
#
# Builds the wheel and sdist, installs the wheel into an EMPTY virtualenv
# OUTSIDE this checkout, and drives it with `cwd` outside the repository and
# `PYTHONPATH` empty. Both of those are the whole point:
#
#   * `pytest.ini` puts `workflows/chinook-nl-to-sql/tools` on `sys.path`
#     in-tree, so a green test suite proves nothing about a wheel;
#   * every module that computed a path from `__file__` "worked" in the
#     checkout and pointed inside site-packages once installed. That is how
#     `platform_list_workflows` came to answer "No workflows exist yet." with
#     the user's workflows sitting right there. Nothing but this proof
#     catches that class of defect, because it is not a crash.
#
# The package used for the proof is scaffolded by the installed CLI itself, so
# it has no lineage in this repository at all, plus a copy of a real package
# that binds NO chinook tool. Exit non-zero on the first failure.
#
# Runs in CI on every pull request (.github/workflows/ci.yml) and before every
# release (.github/workflows/release.yml).

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${OSG_PROOF_DIR:-${TMPDIR:-/tmp}/osg-clean-install}"
VENV="$WORK/venv"
PROJECT="$WORK/project"

rm -rf "$WORK"
mkdir -p "$PROJECT"

echo "==> building sdist + wheel"
rm -rf "$REPO/backend/dist"
python3 -m pip install --quiet --upgrade build twine
python3 -m build --outdir "$REPO/backend/dist" "$REPO/backend"
WHEEL="$(ls "$REPO"/backend/dist/*.whl)"

echo "==> twine check"
python3 -m twine check "$REPO"/backend/dist/*

echo "==> wheel contents"
# One `grep -E` with alternation passed on any single hit, so four required
# files were really one. Checked individually now — `compile/port_specs.json`
# is the generated node catalogue (RC-01), and a wheel without it raises
# `CatalogueError` on the adopter's first import rather than in our CI.
LISTING="$(python3 -m zipfile -l "$WHEEL")"
for required in "py.typed" "LICENSE" "entry_points.txt" "static/chat.html" \
                "compile/port_specs.json"; do
  printf '%s\n' "$LISTING" | grep -qF "$required" \
    || { echo "the wheel is missing package data it must ship: $required"; exit 1; }
done

echo "==> clean venv, core + one provider extra only"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "${WHEEL}[ollama]"

# Nothing below may see this checkout: no cwd inside it, no PYTHONPATH.
run() { (cd "$PROJECT" && env -u PYTHONPATH "$VENV/bin/$@"); }

echo "==> openstategraph --version"
run openstategraph --version

echo "==> import cost: the runtime is lazy, the web layer is absent"
run python -c "
import sys, openstategraph
assert not [m for m in ('langgraph','langchain','fastapi','uvicorn','deepagents','mcp')
            if m in sys.modules], sys.modules.keys()
print('import openstategraph ==', openstategraph.__version__, '— nothing heavy imported')
"

echo "==> a package scaffolded by the installed CLI, with no lineage in this repo"
run openstategraph new proof-package "Proof Package"
run openstategraph validate workflows/proof-package
run openstategraph graph workflows/proof-package | head -3

echo "==> a real package that binds NO chinook tool"
cp -R "$REPO/workflows/page-analytics" "$PROJECT/"
rm -rf "$PROJECT/page-analytics/tests/__pycache__"
run openstategraph validate page-analytics
run openstategraph graph page-analytics | head -3

echo "==> load_workflow, and the runtime imports it did NOT take"
run python -c "
import sys
from openstategraph import load_workflow
workflow = load_workflow('page-analytics')
assert workflow.slug == 'page-analytics'
assert 'fastapi' not in sys.modules and 'deepagents' not in sys.modules and 'mcp' not in sys.modules
print('loaded', workflow.slug, 'with', len(workflow.warnings), 'capability warning(s)')
print(workflow.mermaid().splitlines()[4])
"

echo "==> the workflows root is the project's, never the interpreter's lib/"
run python -c "
from openstategraph.workflows_root import checkout_root, content_root, workflows_root
assert checkout_root() is None, 'the wheel thinks it is inside a checkout'
assert 'site-packages' not in str(workflows_root()), workflows_root()
print('workflows root ->', workflows_root())
print('read jail      ->', content_root())
"

echo "==> a missing extra exits 3 and names its install line"
set +e
(cd "$PROJECT" && env -u PYTHONPATH "$VENV/bin/openstategraph" serve >/dev/null 2>&1)
code=$?
set -e
[ "$code" -eq 3 ] || { echo "expected exit 3 for a missing extra, got $code"; exit 1; }

echo
echo "CLEAN-INSTALL PROOF PASSED — $WHEEL"
