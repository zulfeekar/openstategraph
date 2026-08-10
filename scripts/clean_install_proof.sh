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
# TWO SOURCES, ONE PROOF
#
#   OSG_SOURCE=build   (default) build the wheel from this checkout and prove
#                      that. What every pull request runs.
#   OSG_SOURCE=index   download the wheel from a package index and prove
#                      *that* — the artifact a stranger's `pip install` would
#                      actually fetch. The release train runs this against
#                      TestPyPI after upload and before the PyPI gate, because
#                      a locally-built wheel and a published one are not the
#                      same claim: sdist/wheel selection, index metadata, a
#                      yanked file and a botched upload are all invisible to
#                      the build-mode run.
#
#     OSG_VERSION           required in index mode, e.g. 0.3.0
#     OSG_INDEX_URL         primary index (default https://pypi.org/simple)
#     OSG_EXTRA_INDEX_URL   fallback index (the release train puts TestPyPI
#                           here, NOT in OSG_INDEX_URL — see below)
#     OSG_PIP_PRE           set to 1 to allow pre-release versions
#     OSG_INDEX_RETRIES     attempts while the index catches up (default 10,
#                           15s apart; TestPyPI is not instantly consistent)
#
#   Why TestPyPI is the *extra* index and PyPI the primary: TestPyPI carries
#   stale and squatted copies of ordinary names, and `openstategraph`'s
#   dependencies (langgraph, langchain, pydantic) must come from the real
#   index. Pinning `openstategraph==$OSG_VERSION` — a version that by
#   definition is not yet on PyPI when the rehearsal runs — is what forces the
#   package itself to come from the extra index.
#
# Runs in CI on every pull request (.github/workflows/ci.yml) and twice per
# release (.github/workflows/release.yml): once on the built wheel, once on the
# published one. `docs/releasing.md` is the map.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${OSG_PROOF_DIR:-${TMPDIR:-/tmp}/osg-clean-install}"
VENV="$WORK/venv"
PROJECT="$WORK/project"
SOURCE="${OSG_SOURCE:-build}"

rm -rf "$WORK"
mkdir -p "$PROJECT"

# Index arguments, empty in build mode so the same `pip` lines serve both.
INDEX_ARGS=()
if [ "$SOURCE" = "index" ]; then
  [ -n "${OSG_VERSION:-}" ] || { echo "OSG_SOURCE=index needs OSG_VERSION"; exit 2; }
  INDEX_ARGS+=(--index-url "${OSG_INDEX_URL:-https://pypi.org/simple}")
  # `if`, not `[ … ] && …`: under `set -e` a failing `&&` list at top level
  # exits the script, so the one-liner form would abort whenever the variable
  # happened to be unset — which is the common case.
  if [ -n "${OSG_EXTRA_INDEX_URL:-}" ]; then
    INDEX_ARGS+=(--extra-index-url "$OSG_EXTRA_INDEX_URL")
  fi
  if [ "${OSG_PIP_PRE:-0}" = "1" ]; then
    INDEX_ARGS+=(--pre)
  fi
fi

case "$SOURCE" in
  build)
    # The wheel carries the canvas (scale-and-adopt ticket 01), so the wheel
    # cannot be built before the canvas is. `hatch_build.py` fails the build
    # rather than shipping a visual builder with no visuals; this is where the
    # front end gets built so that failure never happens in CI by surprise.
    if [ ! -f "$REPO/dist/index.html" ]; then
      command -v npm >/dev/null 2>&1 || {
        echo "the editor is not built and npm is not on PATH."
        echo "Install Node.js and run 'npm ci && npm run build', or set"
        echo "OPENSTATEGRAPH_EDITOR_DIST to a directory that already has one."
        exit 1
      }
      echo "==> building the editor (npm run build)"
      (cd "$REPO" && npm ci --silent && npm run build >/dev/null)
    fi

    echo "==> building sdist + wheel"
    rm -rf "$REPO/backend/dist"
    python3 -m pip install --quiet --upgrade build twine
    python3 -m build --outdir "$REPO/backend/dist" "$REPO/backend"
    WHEEL="$(ls "$REPO"/backend/dist/*.whl)"

    echo "==> twine check"
    python3 -m twine check "$REPO"/backend/dist/*
    ;;
  index)
    echo "==> fetching openstategraph==$OSG_VERSION from the index"
    mkdir -p "$WORK/download"
    attempt=1
    until python3 -m pip download --quiet --no-deps --only-binary=:all: \
            "${INDEX_ARGS[@]}" --dest "$WORK/download" \
            "openstategraph==$OSG_VERSION"; do
      if [ "$attempt" -ge "${OSG_INDEX_RETRIES:-10}" ]; then
        echo "openstategraph==$OSG_VERSION never became installable from the index"
        exit 1
      fi
      echo "    not visible yet (attempt $attempt) — the index is catching up"
      attempt=$((attempt + 1))
      sleep 15
    done
    WHEEL="$(ls "$WORK"/download/*.whl)"
    echo "    got $(basename "$WHEEL")"
    ;;
  *)
    echo "OSG_SOURCE must be 'build' or 'index', got '$SOURCE'"; exit 2 ;;
esac

echo "==> wheel contents"
# One `grep -E` with alternation passed on any single hit, so four required
# files were really one. Checked individually now — `compile/port_specs.json`
# is the generated node catalogue (RC-01), and a wheel without it raises
# `CatalogueError` on the adopter's first import rather than in our CI.
LISTING="$(python3 -m zipfile -l "$WHEEL")"
for required in "py.typed" "LICENSE" "entry_points.txt" "static/chat.html" \
                "compile/port_specs.json" "static/editor/index.html"; do
  printf '%s\n' "$LISTING" | grep -qF "$required" \
    || { echo "the wheel is missing package data it must ship: $required"; exit 1; }
done

echo "==> clean venv, core + one provider extra only"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
if [ "$SOURCE" = "index" ]; then
  # The owner's question — "how do you retest before it goes to PyPI" — is
  # answered by this line: resolve and install the way a stranger would,
  # from the index, not from a file we just built.
  "$VENV/bin/pip" install --quiet "${INDEX_ARGS[@]}" \
    "openstategraph[ollama]==$OSG_VERSION"
else
  "$VENV/bin/pip" install --quiet "${WHEEL}[ollama]"
fi

# Nothing below may see this checkout: no cwd inside it, no PYTHONPATH.
run() { (cd "$PROJECT" && env -u PYTHONPATH "$VENV/bin/$@"); }

echo "==> openstategraph --version"
run openstategraph --version
if [ "$SOURCE" = "index" ]; then
  # The rehearsal must prove it tested the version being released, not a
  # neighbour the resolver preferred. `--version` prints "openstategraph X.Y.Z".
  reported="$(run openstategraph --version | tr -d '\r' | awk '{print $NF}')"
  [ "$reported" = "$OSG_VERSION" ] \
    || { echo "installed $reported but the release is $OSG_VERSION"; exit 1; }
fi

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

# ---------------------------------------------------------------------------
# THE PROOF THAT MATTERS FOR ADOPTION (scale-and-adopt ticket 01)
#
# Everything above proves the compiler survives being installed. This proves
# the *product* does: one process, one origin, editor at /, customer chat at
# /chat, API under /api — from a wheel, in a venv, from a directory that has
# never seen this repository. Without it the feature regresses to a 404 in
# silence, because a 404 at / is exactly what "we forgot the package data"
# looks like and nothing else in this file would notice.
#
# `--port 0` on purpose: it is the only mode that cannot accidentally pass by
# landing on the port the editor bundle used to hardcode.
# ---------------------------------------------------------------------------
echo "==> installing the [server] extra (the exit-3 gate above is now satisfied)"
if [ "$SOURCE" = "index" ]; then
  "$VENV/bin/pip" install --quiet "${INDEX_ARGS[@]}" \
    "openstategraph[server]==$OSG_VERSION"
else
  "$VENV/bin/pip" install --quiet "${WHEEL}[server]"
fi

echo "==> openstategraph serve --port 0, from outside the checkout"
SERVE_LOG="$WORK/serve.log"
(cd "$PROJECT" && env -u PYTHONPATH "$VENV/bin/openstategraph" serve --port 0) \
  >"$SERVE_LOG" 2>&1 &
SERVE_PID=$!
# EXIT, not just the happy path: a failed assertion below must not leave a
# server running on the machine that ran this.
trap 'kill "$SERVE_PID" 2>/dev/null || true' EXIT

# The URL it actually landed on, read from the line it promises to print. That
# line IS the contract — `--port 0` is useless if you cannot find out where it
# went — so parsing it is a test of the contract, not a workaround.
BASE=""
for _ in $(seq 1 150); do
  if ! kill -0 "$SERVE_PID" 2>/dev/null; then
    echo "the server exited before it printed a URL:"; cat "$SERVE_LOG"; exit 1
  fi
  # `|| true` because this file runs under `set -o pipefail`: until the line
  # appears, grep exits 1 and would take the whole script down with it.
  BASE="$(grep -m1 '^editor ' "$SERVE_LOG" | awk '{print $2}' | sed 's:/$::' || true)"
  [ -n "$BASE" ] && break
  sleep 0.2
done
[ -n "$BASE" ] || { echo "serve never printed its URL:"; cat "$SERVE_LOG"; exit 1; }
echo "    listening on $BASE"

"$VENV/bin/python" - "$BASE" <<'PY' || { echo "--- serve log ---"; cat "$SERVE_LOG"; exit 1; }
import json
import sys
import time
import urllib.error
import urllib.request

base = sys.argv[1]


def get(path: str, tries: int = 1):
    last = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(base + path, timeout=10) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as exc:  # not listening yet
            last = exc
            time.sleep(0.2)
    raise SystemExit(f"{path} never answered: {last}")


# Readiness first, so nothing below can fail merely for being early.
status, _ = get("/api/health", tries=100)
assert status == 200, f"/api/health returned {status}"

status, body = get("/")
assert status == 200, f"/ returned {status} — the wheel is not serving the editor"
assert 'id="root"' in body, f"/ is not the editor SPA: {body[:300]!r}"
assert "<script" in body, "the editor HTML carries no bundle"
print("    /               the editor SPA (not a 404, not the 'not built' page)")

status, body = get("/chat")
assert status == 200, f"/chat returned {status}"
assert "surface=chat" in body, "/chat is not the customer chat page"
print("    /chat           the customer chat surface")

status, body = get("/api/workflows")
assert status == 200, f"/api/workflows returned {status}"
assert isinstance(json.loads(body), list), "/api/workflows is not a JSON list"
print("    /api/workflows  JSON, served under the same origin")

status, _ = get("/chat/mermaid.js")
assert status == 200, f"/chat/mermaid.js returned {status} — the wheel lost its Mermaid"
print("    /chat/mermaid.js  the flow view's Mermaid, from the wheel, no CDN")
PY

kill "$SERVE_PID" 2>/dev/null || true
wait "$SERVE_PID" 2>/dev/null || true
trap - EXIT

echo
echo "CLEAN-INSTALL PROOF PASSED — $WHEEL"
