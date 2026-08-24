#!/usr/bin/env bash
# The clean-venv proof — wayfinder ticket 06, framework-packaging §3.6.
#
#   scripts/clean_install_proof.sh
#
# Builds the wheel and sdist, installs the wheel into an EMPTY virtualenv
# OUTSIDE this checkout, and drives it with `cwd` outside the repository and
# `PYTHONPATH` empty. Both of those are the whole point:
#
#   * `pytest.ini` puts `workflows/chinook-assistant/tools` on `sys.path`
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
#                           15s apart via OSG_INDEX_RETRY_DELAY; TestPyPI is
#                           not instantly consistent). Applies to the initial
#                           download AND to the two `pip install` calls below
#                           it — a version minutes old can still 404 on any of
#                           them (launch-readiness 37). Every index-mode pip
#                           call also passes --no-cache-dir, because a stale
#                           local copy of the simple index page is a second,
#                           independent way to get the same wrong "no such
#                           version" error. See scripts/lib/pip_retry.sh.
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
# shellcheck source=scripts/lib/pip_retry.sh
source "$REPO/scripts/lib/pip_retry.sh"
WORK="${OSG_PROOF_DIR:-${TMPDIR:-/tmp}/osg-clean-install}"
VENV="$WORK/venv"
PROJECT="$WORK/project"
SOURCE="${OSG_SOURCE:-build}"

rm -rf "$WORK"
mkdir -p "$PROJECT"

# Index arguments, empty in build mode so the same `pip` lines serve both.
# `--no-cache-dir` is load-bearing here, not cosmetic: pip caches the simple
# index page, so a version published seconds ago can be reported as
# nonexistent from a page fetched before the upload (launch-readiness 37,
# "stranger run three" — `--no-cache-dir` alone fixed it there). The
# `pip_retry` polling below handles the *other* cause, the index itself not
# having propagated yet; this handles the local one. Both apply.
INDEX_ARGS=()
if [ "$SOURCE" = "index" ]; then
  [ -n "${OSG_VERSION:-}" ] || { echo "OSG_SOURCE=index needs OSG_VERSION"; exit 2; }
  INDEX_ARGS+=(--no-cache-dir)
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
    pip_retry "openstategraph==$OSG_VERSION" \
      python3 -m pip download --quiet --no-deps --only-binary=:all: \
        "${INDEX_ARGS[@]}" --dest "$WORK/download" \
        "openstategraph==$OSG_VERSION"
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
# `templates/` is package data too (scale-and-adopt ticket 04): the whole point
# of shipping starting points is that someone who never cloned this repository
# has one, so a wheel without them is a wheel whose `--template` flag lies.
#
# `examples/` is the same claim for the gallery (workflow-gallery ticket 07,
# closing canvas-feels-right 04). Three entries, and each is a different way the
# package data can go missing: the index the catalogue is read from, a document,
# and `sql-qa`'s 1 MB database — the one file big enough that somebody will
# eventually be tempted to exclude it, at which point the only example with a
# machine-gradable eval stops working on arrival.
for required in "py.typed" "LICENSE" "entry_points.txt" "static/chat.html" \
                "compile/port_specs.json" "static/editor/index.html" \
                "templates/index.json" "templates/minimal/workflow.json" \
                "templates/minimal/AGENTS.md" "templates/routed-qa/workflow.json" \
                "templates/team/workflow.json" \
                "examples/index.json" "examples/chained-summarizer/workflow.json" \
                "examples/chained-summarizer/AGENTS.md" \
                "examples/sql-qa/data/Chinook_Sqlite.sqlite"; do
  # No pipe here on purpose: `printf | grep -q` lets grep exit at first
  # match while printf is mid-write — SIGPIPE, which pipefail turns into a
  # nondeterministic failure (it did, on the second-ever CI run).
  grep -qF "$required" <<<"$LISTING" \
    || { echo "the wheel is missing package data it must ship: $required"; exit 1; }
done

echo "==> clean venv, core + one provider extra only"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
if [ "$SOURCE" = "index" ]; then
  # The owner's question — "how do you retest before it goes to PyPI" — is
  # answered by this line: resolve and install the way a stranger would,
  # from the index, not from a file we just built.
  pip_retry "openstategraph[ollama]==$OSG_VERSION" \
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

# Ticket 04: the templates are only real if they scaffold from the *wheel*, in
# a directory that has never seen this checkout. Every one of them, because a
# template nobody instantiates here is a template whose files could be missing
# from the artifact and nothing would say so until an adopter tried it.
echo "==> every template in the wheel scaffolds, validates and compiles"
run openstategraph new --list-templates
for template in $(run openstategraph new --list-templates | awk '{print $1}'); do
  run openstategraph new "proof-$template" --template "$template"
  run openstategraph validate "workflows/proof-$template"
  run openstategraph graph "workflows/proof-$template" >/dev/null
  test -s "$PROJECT/workflows/proof-$template/AGENTS.md" \
    || { echo "the $template template scaffolded no AGENTS.md"; exit 1; }
  echo "    $template  ok"
done

# Gallery ticket 07. The templates prove a *rendered* starting point survives
# the wheel; this proves a whole **package** does — and it is a different claim,
# because an example carries tests, a knowledge store, an eval fixture and a
# database, none of which a document import would bring. `nested-mounts` is the
# one to copy: it is three deep, so a copy that forgot a dependency produces a
# document whose mount cannot resolve, and `validate` says so.
echo "==> the shipped examples list, copy with their mounts, and validate"
run openstategraph examples list | head -4
run openstategraph examples copy nested-mounts
for slug in nested-mounts nested-mounts-mid chained-summarizer; do
  test -f "$PROJECT/workflows/$slug/workflow.json" \
    || { echo "copying nested-mounts left out $slug"; exit 1; }
  run openstategraph validate "workflows/$slug" >/dev/null
done
echo "    nested-mounts + 2 mounted packages, all VALID"

# The copy is what makes an example runnable, and this is the sharpest case:
# `sql-qa`'s three tools jail their database path inside the workflows root, so
# the package is inert where it ships and live once copied. If that ever stops
# being true, it will be because someone widened the jail into site-packages.
run openstategraph examples copy sql-qa
run python -c "
from openstategraph import examples
from openstategraph.prebuilt_sql import _resolve_database

assert 'site-packages' in str(examples.DATA), examples.DATA
resolved = _resolve_database('sql-qa/data/Chinook_Sqlite.sqlite')
assert resolved is not None, 'the copied database is refused by the jail'
assert 'site-packages' not in str(resolved), resolved
print('    sql-qa copied, and its database opens from the project ->', resolved.name)
"

echo "==> a real package, copied whole, resolving its own tools"
# The one visible example. It used to bind no Chinook tool at all — it mounted
# a second package that owned them — so this step proved a wheel could compile
# it with the chinook tool package absent. One-chinook ticket 10 collapsed the
# two, and the claim is now the stronger one: the package carries its own
# `tools/`, `data/` and `knowledge/`, so copying the directory is the whole
# transfer and discovery resolves the three SQL tools from inside the copy —
# no path into this checkout, and nothing bundled in the wheel.
cp -R "$REPO/workflows/chinook-assistant" "$PROJECT/"
run openstategraph validate chinook-assistant
run openstategraph graph chinook-assistant | head -3

echo "==> load_workflow, and the runtime imports it did NOT take"
run python -c "
import sys
from openstategraph import load_workflow
workflow = load_workflow('chinook-assistant')
assert workflow.slug == 'chinook-assistant'
assert 'fastapi' not in sys.modules and 'deepagents' not in sys.modules and 'mcp' not in sys.modules
print('loaded', workflow.slug, 'with', len(workflow.warnings), 'capability warning(s)')
print(workflow.mermaid().splitlines()[4])
"

# ---------------------------------------------------------------------------
# THE GRAPH ACTUALLY RUNS (added after a wheel audit, 2026-08-13)
#
# Everything above compiles, validates, draws and serves. Until this step
# nothing in this file had ever *executed* a workflow — and that gap was not
# theoretical. Three defects lived in it, all found by hand in a venv:
#
#   - `openstategraph run` with no credential printed an empty line and exited
#     **0**. A new user's literal first command after `new`, reported as a
#     success.
#   - `graph` demanded the resolved provider's integration package in order to
#     draw a Mermaid diagram, so a venv holding only [ollama] could not draw a
#     document that resolved to Anthropic.
#   - `serve` died on an empty OPENSTATEGRAPH_LOG_LEVEL — the value
#     `.env.example` ships — after printing its URLs, so it read as a server
#     that had started.
#
# A fake model, not a real one: this must pass on a clean machine with no
# credential, no network and no provider account. What is proven is that the
# *runtime* installed from the wheel executes a compiled graph — the
# supersteps, the state channels, the node factories — not that a vendor
# answers. `load_workflow(model=...)` is the documented seam for exactly this.
# ---------------------------------------------------------------------------
echo "==> the runtime executes a graph, from the wheel, with no credential"
run python -c "
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from openstategraph import load_workflow

# A subclass rather than GenericFakeChatModel itself: that one raises on
# bind_tools, and create_agent binds tools for any agent that has them.
class Fixed(GenericFakeChatModel):
    def __init__(self, text):
        super().__init__(messages=iter([]))
        object.__setattr__(self, 'text', text)
    def _generate(self, messages, stop=None, run_manager=None, **kw):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])
    def bind_tools(self, tools, **kw):
        return self

workflow = load_workflow('workflows/proof-minimal', model=Fixed('PROOF-ANSWER-42'))
answer = workflow.ask('what is the answer?')

assert str(answer) == 'PROOF-ANSWER-42', repr(str(answer))
assert answer.outputs, 'the run recorded no node outputs'
assert not answer.warnings, answer.warnings
print('ran ->', repr(str(answer)), 'across', len(answer.outputs), 'node(s)')
"

# The other half, and the one that was actually broken: a run that CANNOT work
# must say so and fail. It exited 0 with an empty answer, and the diagnosis sat
# in `outputs` where only --json would show it.
echo "==> a run with no credential fails loudly rather than silently"
set +e
no_creds="$(cd "$PROJECT" && env -u PYTHONPATH -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u OLLAMA_API_KEY -u OLLAMA_HOST "$VENV/bin/openstategraph" run workflows/proof-minimal "does this fail loudly?" 2>&1)"
code=$?
set -e
[ "$code" -ne 0 ] || {
  echo "a credential-less run exited 0 — it is silently succeeding again"
  echo "$no_creds"
  exit 1
}
case "$no_creds" in
  *API_KEY*) : ;;
  *) echo "the failure named no environment variable to set:"; echo "$no_creds"; exit 1 ;;
esac
echo "    exited $code, naming the variable to set"

# ---------------------------------------------------------------------------
# BEHAVIOUR, NOT WIRING (providers-and-credentials ticket 05)
#
# Everything above proves the artifact is assembled: the files are in the
# wheel, the paths resolve outside the checkout, the commands exit 0. None of
# it asks whether the product still *behaves*. Every behaviour below is
# covered by a unit test in the checkout and by nothing at all in the artifact
# a stranger installs, and the two are not the same claim — `pytest.ini` puts a
# workflow's `tools/` on `sys.path` in-tree, so a green suite is silent about
# exactly the class of defect this file exists for.
#
# Credential-free by construction. The sibling ticket 03's framing is the rule:
# *absent* and *wrong* are testable with no credential at all, and only *valid*
# needs one. A proof that needs a vendor account is a proof that stops running.
# ---------------------------------------------------------------------------

# `backend/tests/public_api.txt` is the semver-public surface, snapshotted —
# but the snapshot test runs against the source tree, so it is silent about a
# name that exists in the checkout and is not SHIPPED. Build mode only: in
# index mode the wheel is a released version and this checkout's snapshot may
# legitimately describe a different one, and a proof that fails for being
# ahead of the release is a proof people learn to ignore.
if [ "$SOURCE" = "build" ]; then
  echo "==> every name the public surface promises is importable from the wheel"
  (cd "$PROJECT" && env -u PYTHONPATH "$VENV/bin/python" - \
     "$REPO/backend/tests/public_api.txt" <<'SURFACE')
import importlib
import sys

missing = []
names = set()
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    dotted = line.split(" = ")[0].split(" ")[0]
    module, _, attribute = dotted.rpartition(".")
    names.add((module, attribute))

for module, attribute in sorted(names):
    try:
        imported = importlib.import_module(module)
    except Exception as exc:
        missing.append(f"{module} does not import: {exc}")
        continue
    if not hasattr(imported, attribute):
        missing.append(f"{module}.{attribute}")

assert names, "the snapshot parsed to nothing — the parser, not the wheel"
assert not missing, "the wheel does not ship what the public API promises: " + repr(missing)
print(f"    {len(names)} public names, all present in the installed package")
SURFACE
fi

echo "==> a package that travelled without its tools/ fails validate, from the wheel"
# `d7b0473`. This is the assertion that would pass in-tree and fail from a
# wheel, which is the valuable kind: in the checkout `pytest.ini` has already
# put `workflows/chinook-assistant/tools` on `sys.path`, so the bindings
# resolve for a reason the adopter does not have. A document arriving without
# its package — a copy, an export, a colleague's file — is the normal case, and
# `validate` is what a person runs on arrival.
STRAYED="$PROJECT/strayed"
rm -rf "$STRAYED"
cp -R "$PROJECT/chinook-assistant" "$STRAYED"
rm -rf "$STRAYED/tools"
set +e
(cd "$PROJECT" && env -u PYTHONPATH "$VENV/bin/openstategraph" validate strayed) \
  >"$WORK/strayed.log" 2>&1
code=$?
set -e
[ "$code" -eq 1 ] || {
  echo "validate exited $code on an unresolvable tool binding, expected 1"
  cat "$WORK/strayed.log"; exit 1; }
grep -q "nothing in this installation implements" "$WORK/strayed.log" || {
  echo "validate failed without naming the unimplemented tool type:"
  cat "$WORK/strayed.log"; exit 1; }
grep -q "tools/" "$WORK/strayed.log" || {
  echo "the refusal does not say what to do about it:"
  cat "$WORK/strayed.log"; exit 1; }
rm -rf "$STRAYED"
echo "    exited $code, naming the three unbound tool types and the fix"

# ---------------------------------------------------------------------------
# THE THREE THAT NEEDED A FIXTURE (providers-and-credentials ticket 07)
#
# Ticket 05 stopped short of these because each needs a document that no
# template scaffolds. They are built here, by the script, on purpose: a
# deliberately broken package committed into `workflows/` is a package some
# other sweep trips over, and one authored in `$PROJECT` is gone with the
# temporary directory.
# ---------------------------------------------------------------------------

echo "==> a legally-empty run exits 0, silent node and all"
# `8bda508`, and the sharpest of the four. `RunResult.warnings` is the run's
# whole health report and `.failures` is the half a script may gate on;
# `cli.run_exit_code` reads `.failures`. The regression is silent: point it at
# `.warnings` and every run containing a *silent node* — a node that ran and
# produced nothing, which this project's own rule says is a report about how
# the answer was reached and not a failed run — starts exiting 1.
#
# The fixture is two nodes and an empty question, so no model is resolved and
# no credential is consulted: `in1` produces nothing, `out1` substitutes
# NO_ANSWER_PRODUCED, and the run is *both* halves of the exit-code condition
# at once except that nothing actually went wrong. That is the only shape that
# tells the two channels apart.
mkdir -p "$PROJECT/workflows/proof-quiet"
cat >"$PROJECT/workflows/proof-quiet/workflow.json" <<'QUIET'
{"version": 1, "name": "Proof Quiet", "published": false,
 "document": {"version": 3, "name": "Proof Quiet", "settings": {},
  "nodes": [{"id": "in1", "type": "input.text", "data": {}, "position": {"x": 40, "y": 200}},
            {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 380, "y": 200}}],
  "edges": [{"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "out1", "portId": "result"}}]}}
QUIET
set +e
quiet="$(cd "$PROJECT" && env -u PYTHONPATH -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL \
  -u OPENAI_API_KEY -u OLLAMA_API_KEY -u OLLAMA_HOST \
  "$VENV/bin/openstategraph" run workflows/proof-quiet "" --json 2>"$WORK/quiet.err")"
code=$?
set -e
[ "$code" -eq 0 ] || {
  echo "a legally-empty run exited $code — a silent node is reaching the failure channel"
  echo "$quiet"; cat "$WORK/quiet.err"; exit 1; }
# And the other direction, or the assertion above passes on a run that never
# had a silent node to fold in and proves nothing at all. The silence is read
# out of `--json`, not off stderr: `--json` is the machine channel and the
# report goes into it rather than being printed twice.
"$VENV/bin/python" - "$quiet" <<'QUIETJSON'
import json, sys
result = json.loads(sys.argv[1])
silent = [line for line in result["warnings"] if "produced no output" in line]
assert silent, f"the run reported no silent node, so exiting 0 proves nothing: {result['warnings']}"
assert "without producing an answer" in result["answer"], result["answer"]
print("    exit 0 with a silent node reported and no answer — report, not failure")
QUIETJSON

echo "==> validate exits 1 on a mount cycle, from the wheel"
# `da44407`. Ticket 05 covered the sibling case (a package copied without its
# `tools/`); this one needs two documents authored to mount each other, which
# no template and no example provides. A cycle can never terminate, so the
# refusal has to arrive at `validate` — the compiler would otherwise recurse
# until Python's own stack said something unhelpful about recursion depth.
for pair in "proof-ouro-a proof-ouro-b" "proof-ouro-b proof-ouro-a"; do
  set -- $pair
  mkdir -p "$PROJECT/workflows/$1"
  cat >"$PROJECT/workflows/$1/workflow.json" <<OURO
{"version": 1, "name": "$1", "published": false,
 "document": {"version": 3, "name": "$1", "settings": {},
  "nodes": [{"id": "in1", "type": "input.text", "data": {}, "position": {"x": 40, "y": 200}},
            {"id": "m1", "type": "workflow.subgraph", "data": {"workflow": "$2"}, "position": {"x": 380, "y": 200}},
            {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 720, "y": 200}}],
  "edges": [{"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "m1", "portId": "task"}},
            {"source": {"nodeId": "m1", "portId": "answer"}, "target": {"nodeId": "out1", "portId": "result"}}]}}
OURO
done
set +e
(cd "$PROJECT" && env -u PYTHONPATH "$VENV/bin/openstategraph" validate workflows/proof-ouro-a) \
  >"$WORK/ouro.log" 2>&1
code=$?
set -e
[ "$code" -eq 1 ] || {
  echo "validate exited $code on a mount cycle, expected 1"; cat "$WORK/ouro.log"; exit 1; }
grep -q "mount cycle" "$WORK/ouro.log" || {
  echo "validate failed without naming the cycle:"; cat "$WORK/ouro.log"; exit 1; }
grep -q "proof-ouro-a -> proof-ouro-b -> proof-ouro-a" "$WORK/ouro.log" || {
  echo "the refusal does not print the cycle it found:"; cat "$WORK/ouro.log"; exit 1; }
rm -rf "$PROJECT/workflows/proof-ouro-a" "$PROJECT/workflows/proof-ouro-b"
echo "    exited $code, printing the two-package cycle it walked"

echo "==> a saved settings.recursionLimit reaches the graph"
# `5543a90`. The number was held at four layers and read at none, so every run
# took 50 whatever the document said — a defect with no symptom until a
# runaway loop costs somebody money.
#
# The loop is a real one — agent, grader, `revise` back to the agent — driven
# by a fake model that answers `fail` to everything, so the grader never
# passes and only the budget can stop it. `maxAttempts` is set past the budget
# on purpose: the grader's own attempt ceiling would otherwise end the loop
# first and the assertion would be about that instead.
#
# **This block used to assert `GraphRecursionError`, and that assertion went
# stale rather than the feature breaking** (`launch-readiness` 14). Until
# `organisms-first-class` 56 a starved loop crashed, and the exception printed
# the limit it hit — so 10 could only have come from the document, and the
# crash was the whole observable. 56 replaced it with the `RemainingSteps`
# guard `CLAUDE.md` has asked for since the cycles section was written: the
# grader force-passes, the wired `pass` edge runs, and the answer is published.
# The loop still terminates and is still bounded; only the evidence moved.
#
# So the proof is now a *comparison*, because publishing an answer is what a
# run at the default 50 does too. Two runs of the same fixture — the document's
# number, then `DEFAULT_STEP_BUDGET` — and the saved one must buy strictly
# fewer attempts. Compared rather than pinned to literals (3 and 23 today), so
# the claim stays *the document's number was read* rather than *a lap costs
# exactly this much*, which the floor constant or a node count could move.
mkdir -p "$PROJECT/workflows/proof-loop"
cat >"$PROJECT/workflows/proof-loop/workflow.json" <<'LOOP'
{"version": 1, "name": "Proof Loop", "published": false,
 "document": {"version": 3, "name": "Proof Loop", "settings": {"recursionLimit": 10},
  "nodes": [{"id": "in1", "type": "input.text", "data": {}, "position": {"x": 40, "y": 200}},
            {"id": "agent1", "type": "agent.llm", "data": {}, "position": {"x": 380, "y": 200}},
            {"id": "grader1", "type": "route.grader", "data": {"maxAttempts": 50}, "position": {"x": 720, "y": 200}},
            {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 1060, "y": 200}}],
  "edges": [{"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "agent1", "portId": "prompt"}},
            {"source": {"nodeId": "agent1", "portId": "result"}, "target": {"nodeId": "grader1", "portId": "candidate"}},
            {"source": {"nodeId": "grader1", "portId": "revise"}, "target": {"nodeId": "agent1", "portId": "feedback"}},
            {"source": {"nodeId": "grader1", "portId": "pass"}, "target": {"nodeId": "out1", "portId": "result"}}]}}
LOOP
run python -c "
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from openstategraph import load_workflow
from openstategraph.step_budget import DEFAULT_STEP_BUDGET

class Fixed(GenericFakeChatModel):
    def __init__(self, text):
        super().__init__(messages=iter([]))
        object.__setattr__(self, 'text', text)
    def _generate(self, messages, stop=None, run_manager=None, **kw):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])
    def bind_tools(self, tools, **kw):
        return self

CAP = 50
assert DEFAULT_STEP_BUDGET != 10, 'the default moved onto the fixture — pick another number'
workflow = load_workflow('workflows/proof-loop', model=Fixed('fail\nnever good enough'))
saved = workflow.ask('go')
default = workflow.ask('go', recursion_limit=DEFAULT_STEP_BUDGET)

budget_stop = [line for line in saved.warnings if 'step budget' in line]
assert budget_stop, 'the run does not say the step budget stopped it: ' + repr(saved.warnings)
assert not [line for line in saved.warnings if 'ran out of attempts' in line], (
    'the budget stop is dressed as an attempt cap: ' + repr(saved.warnings))
assert saved.attempts < CAP, 'the grader hit its own cap, so this proves nothing about the budget: ' + repr(saved.attempts)
assert saved.attempts < default.attempts, (
    'the saved 10 bought as many attempts as the default ' + repr(DEFAULT_STEP_BUDGET) +
    ', so the document was not read: ' + repr((saved.attempts, default.attempts)))
print('    the document\'s 10 bought', saved.attempts, 'attempts where the default', DEFAULT_STEP_BUDGET, 'buys', default.attempts)
"
rm -rf "$PROJECT/workflows/proof-loop"

echo "==> user-scoped memory refuses a run the server identified nobody for"
# providers-and-credentials ticket 01. The namespace is keyed on the principal
# the *server* determined, and when it determined nobody there is nowhere to
# put a fact about a person. This used to fold to a shared "anonymous"
# namespace, which is a merge rather than a degradation: two strangers reading
# each other's remembered facts, silently. Both directions, because a refusal
# that also refuses an identified run proves nothing.
run python -c "
from langgraph.graph import StateGraph, START, END
from langgraph.store.memory import InMemoryStore
from typing_extensions import TypedDict

from openstategraph.memory import USER_MEMORY_NAMESPACE, memory_tools

save = {tool.name: tool for tool in memory_tools()}['save_memory']

class State(TypedDict):
    said: str

builder = StateGraph(State)
builder.add_node('remember', lambda state: {
    'said': save.invoke({'fact': 'the user drinks tea', 'scope': 'user'})
})
builder.add_edge(START, 'remember')
builder.add_edge('remember', END)
store = InMemoryStore()
graph = builder.compile(store=store)

# Nobody identified: no principal resolver is configured, so the server put no
# user_email in configurable.
said = graph.invoke({'said': ''}, config={'configurable': {}})['said']
assert said.startswith('NOT SAVED'), said
assert not list(store.search((USER_MEMORY_NAMESPACE,))), 'it wrote somewhere anyway'

# And the other direction, or the assertion above is satisfied by a scope that
# never works.
said = graph.invoke({'said': ''}, config={'configurable': {'user_email': 'a@b.c'}})['said']
assert said == 'Remembered (user).', said
spaces = [item.namespace for item in store.search((USER_MEMORY_NAMESPACE,))]
assert spaces == [('memories', 'a@b_c')], spaces
print('    anonymous -> NOT SAVED, nothing written; identified -> one namespace')
"

echo "==> the workflows root is the project's, never the interpreter's lib/"
run python -c "
from openstategraph.workflows_root import checkout_root, content_root, workflows_root
assert checkout_root() is None, 'the wheel thinks it is inside a checkout'
assert 'site-packages' not in str(workflows_root()), workflows_root()
print('workflows root ->', workflows_root())
print('read jail      ->', content_root())
"

# Scale-and-adopt tickets 02 and 03, and this file is the only place either can
# actually be proven: both are claims about the INSTALLED process specifically.
# `state_dir()`'s installed branch is unreachable in the test suite except by
# monkeypatching `checkout_root`, and "listing does not import the runtime" is
# only interesting in a venv where the runtime is a real, separate install.
echo "==> the catalogue lists without compiling, and writes nothing into the project"
run python -c "
import sys
from openstategraph import Workflows
from openstategraph.state_dir import state_dir
from openstategraph.workflows_root import workflows_root

catalog = Workflows()
rows = catalog.list()
assert any(row.slug == 'proof-package' for row in rows), rows
assert not [m for m in ('langgraph', 'langchain') if m in sys.modules], (
    'listing imported the runtime — it compiled something'
)
assert catalog.root == workflows_root(), catalog.root

# Ticket 03: pointing at a directory must not write into it. Installed, the
# state dir is the platform's per-user one, so nothing this process persists
# can land in the adopter's project — including on a read-only mount.
where = state_dir()
assert not str(where).startswith(str(catalog.root)), where
assert 'site-packages' not in str(where), where
print('catalogue ->', len(rows), 'workflow(s) listed, nothing compiled')
print('state dir ->', where)
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
  pip_retry "openstategraph[server]==$OSG_VERSION" \
    "$VENV/bin/pip" install --quiet "${INDEX_ARGS[@]}" \
      "openstategraph[server]==$OSG_VERSION"
else
  "$VENV/bin/pip" install --quiet "${WHEEL}[server]"
fi

echo "==> openstategraph serve --port 0, from outside the checkout"
SERVE_LOG="$WORK/serve.log"
# `exec` is load-bearing, and its absence used to leak a server on every run.
# Without it `$!` is the SUBSHELL's pid, so the `kill` below reaps the subshell
# and leaves the actual uvicorn process alive and holding its port and its
# state directory. Nobody noticed while the leak was harmless; the ticket-06
# serve lock turned it into "another OpenStateGraph server already holds …" on
# the second launch below, which is exactly what that lock is for.
# Its own state directory (ticket 06). `state_dir()`'s real answer — the
# platform per-user directory, keyed by project — is asserted above and stays
# asserted; but the *serve lock* is scoped to that directory, so two proof runs
# on one machine (a CI matrix, two developers, two sessions) would refuse each
# other for a reason that has nothing to do with the wheel. A hermetic run
# needs a hermetic state directory.
# Every provider credential unset, deliberately (ticket 05). CI has none, so
# this changes nothing there; a developer's shell has several, and the
# behavioural section below asserts what a run does when the key is MISSING.
# Inheriting a key would turn that assertion into a real vendor call — slow,
# networked, and passing for the wrong reason on the one machine most likely
# to run this by hand.
(cd "$PROJECT" && exec env -u PYTHONPATH \
  -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u OLLAMA_API_KEY \
  -u OLLAMA_HOST -u OLLAMA_ENDPOINT \
  OPENSTATEGRAPH_STATE_DIR="$WORK/state" \
  "$VENV/bin/openstategraph" serve --port 0) \
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


# ---------------------------------------------------------------------------
# THE SAME SERVER, ASKED ABOUT BEHAVIOUR (providers-and-credentials ticket 05)
#
# The block above proves the four surfaces answer. This one proves they answer
# *correctly*, on the three questions that are contract rather than wiring —
# each one a single call against the server already running, and none of them
# needing a credential. Ticket 05's original list, closed from the outside for
# the first time.
# ---------------------------------------------------------------------------
echo "==> the server behaves, not merely answers"
(cd "$PROJECT" && "$VENV/bin/python" - "$BASE" <<'BEHAVE') || { echo "--- serve log ---"; cat "$SERVE_LOG"; exit 1; }
import json
import sys
import urllib.error
import urllib.request

base = sys.argv[1]


def call(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        base + path, data=body, method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


document = json.loads(
    open("workflows/proof-minimal/workflow.json", encoding="utf-8").read()
)

# 1. The contract break. `user_email` was a field on `RunRequest`, typed into a
#    box in /chat and copied into `configurable` unverified, where it keyed a
#    per-person memory namespace — so any client could read and write any
#    person's memories by naming them. It is `extra: forbid` now, and this is
#    the one assertion that would have caught the break from the outside.
status, body = call("POST", "/api/runs", {
    "workflow": document, "question": "hi", "user_email": "someone@else.example",
})
assert status == 422, f"a client naming the person got {status}, not 422: {body[:300]}"
assert "user_email" in body, body[:300]
print("    /api/runs        422 — a client may not say who a run is for")

# 2. A missing provider key is a diagnosis, not a 500 and not a silence. The
#    customer surface gets a sentence it can act on; the developer audience
#    gets the variable to set. Both halves, because a 200 whose developer
#    channel is empty is the shape ticket 04 already had to fix once.
status, body = call("POST", "/api/runs", {
    "workflow": document, "question": "hi", "audience": "developer",
})
assert status == 200, f"a credential-less run returned {status}: {body[:300]}"
answer = json.loads(body)
warnings = " ".join((answer.get("developer") or {}).get("warnings") or [])
assert "no credential" in warnings, f"no credential diagnosis: {warnings!r}"
assert "OLLAMA_API_KEY" in warnings, f"the diagnosis names no variable: {warnings!r}"
assert answer.get("answer"), "a failed run answered with nothing at all"
print("    /api/runs        200 + the variable to set, not a 500 and not a blank")

# 2b. `ThreadSummary.failed` on the wire (`f46935e`, ticket 07). The run just
#     above failed a node for want of a credential, and the checkpointer wrote
#     it down; this reads it back through the API a history list actually
#     calls. `failed` is deliberately NOT folded into `status` — a failed run
#     is not paused, and every reader of `status == "finished"` would have had
#     to learn a third case — so a regression here is a boolean quietly going
#     missing rather than an endpoint breaking, and nothing else would notice.
#
#     Ticket 07 expected this to need the `[sqlite]` extra. It does not: the
#     saver is in-memory and this is the same process that ran the run, which
#     is exactly the reader a history list is. Durability across a restart is a
#     different claim and not this one.
thread_id = json.loads(body)["thread_id"]
status, body = call("GET", "/api/threads")
assert status == 200, f"/api/threads returned {status}: {body[:300]}"
threads = {row["thread_id"]: row for row in json.loads(body)["threads"]}
assert thread_id in threads, f"the run left no thread: {sorted(threads)}"
assert threads[thread_id]["failed"] is True, threads[thread_id]
# The other direction, or `failed` could be hardcoded true and still pass.
assert threads[thread_id]["status"] == "finished", threads[thread_id]
print("    /api/threads     the failed run is readable back, failed=True")

# 3. The body the API hands you is a body it takes back. A GET whose response
#    a PUT rejects is a round trip that does not close, and every client that
#    reads-modifies-writes a document rides on it.
status, body = call("GET", "/api/workflows/proof-minimal")
assert status == 200, f"GET returned {status}"
fetched = json.loads(body)
status, put = call("PUT", "/api/workflows/proof-minimal", fetched)
assert status == 200, f"the API refused the body it just handed out: {status} {put[:300]}"
assert json.loads(put)["document"] == fetched["document"], "the round trip changed it"
print("    /api/workflows   GET -> PUT round-trips unchanged")
BEHAVE

kill "$SERVE_PID" 2>/dev/null || true
wait "$SERVE_PID" 2>/dev/null || true
trap - EXIT

# --------------------------------------------------------------------------
# The two ticket-06 deployment guarantees, proven from the INSTALLED WHEEL and
# not from the checkout — which is the point of this script: a refusal that
# only fires in a source tree is not a refusal a deployer ever gets.

echo "==> more than one worker is refused, not warned about"
set +e
(cd "$PROJECT" && env -u PYTHONPATH "$VENV/bin/openstategraph" serve --workers 4) \
  >"$WORK/workers.log" 2>&1
code=$?
set -e
[ "$code" -ne 0 ] || { echo "serve --workers 4 exited 0"; cat "$WORK/workers.log"; exit 1; }
grep -q -- "--workers 1" "$WORK/workers.log" || {
  echo "the refusal does not say what to do instead:"; cat "$WORK/workers.log"; exit 1; }
grep -qi "catalogue" "$WORK/workers.log" || {
  echo "the refusal names only one of the two causes:"; cat "$WORK/workers.log"; exit 1; }
echo "    serve --workers 4 -> exit $code, naming both causes and the fix"

set +e
(cd "$PROJECT" && env -u PYTHONPATH WEB_CONCURRENCY=4 \
  "$VENV/bin/openstategraph" serve) >"$WORK/concurrency.log" 2>&1
code=$?
set -e
[ "$code" -ne 0 ] || {
  echo "WEB_CONCURRENCY=4 was accepted"; cat "$WORK/concurrency.log"; exit 1; }
echo "    WEB_CONCURRENCY=4 -> exit $code"

echo "==> the shared token gate works from the wheel"
TOKEN="proof-token-$$"
TOKEN_LOG="$WORK/token-serve.log"
(cd "$PROJECT" && exec env -u PYTHONPATH OPENSTATEGRAPH_API_TOKEN="$TOKEN" \
  OPENSTATEGRAPH_STATE_DIR="$WORK/state" \
  "$VENV/bin/openstategraph" serve --port 0) >"$TOKEN_LOG" 2>&1 &
SERVE_PID=$!
trap 'kill "$SERVE_PID" 2>/dev/null || true' EXIT
BASE=""
for _ in $(seq 1 100); do
  BASE="$(grep -m1 '^editor ' "$TOKEN_LOG" | awk '{print $2}' | sed 's:/$::' || true)"
  [ -n "$BASE" ] && break
  sleep 0.2
done
[ -n "$BASE" ] || {
  echo "the gated server never printed its URL:"; cat "$TOKEN_LOG"; exit 1; }

# One line: a here-document body starts on the line after the *whole* command,
# so splitting the `|| { … }` across lines would swallow it into the script.
"$VENV/bin/python" - "$BASE" "$TOKEN" <<'GATE' || { echo "--- serve log ---"; cat "$TOKEN_LOG"; exit 1; }
import sys
import time
import urllib.error
import urllib.request

base, token = sys.argv[1], sys.argv[2]


def call(path, header=None, tries=1):
    request = urllib.request.Request(base + path)
    if header:
        request.add_header("Authorization", header)
    last = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except (urllib.error.URLError, OSError) as exc:  # not listening yet
            last = exc
            time.sleep(0.2)
    raise SystemExit("%s never answered: %s" % (path, last))


assert call("/api/health", tries=100) == 200, "a liveness probe must stay open"
assert call("/api/workflows") == 401, "the gate did not refuse an anonymous call"
assert call("/api/workflows", "Bearer " + token) == 200, "a valid token was refused"
assert call("/api/workflows", "Bearer wrong") == 401, "a wrong token was accepted"
assert call("/login") == 200, "there is no way for a browser to sign in"
print("    /api/workflows  401 anonymous, 200 with the bearer token")
print("    /api/health     200 without one (a probe carries no credentials)")
GATE

kill "$SERVE_PID" 2>/dev/null || true
wait "$SERVE_PID" 2>/dev/null || true
trap - EXIT

echo
echo "CLEAN-INSTALL PROOF PASSED — $WHEEL"
