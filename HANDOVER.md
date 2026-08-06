# Handover — Dyflow

Written 2026-08-06 for a fresh agent (or fresh session) picking this project up cold. Read this first, then go to the source-of-truth documents it points at — this file summarizes, it does not replace them.

## What this project is

A visual AI-workflow builder: a TypeScript/React/JointJS canvas editor (`src/`) that compiles a canvas-authored `workflow.json` document into a real Python LangGraph `StateGraph` (`backend/`) and runs it. Not a runtime we wrote ourselves — we compile to LangGraph and inherit its checkpointing, streaming, `Send` fan-out, and reducer semantics. See CLAUDE.md's "We are a compiler, not a runtime" section.

## Read these, in this order

1. **`CLAUDE.md`** (repo root) — architecture principles, non-negotiables (no god classes, the Interface→Abstract→Base→Concrete ladder, LangGraph vocabulary, the reducer-hazard rule, portability guardrails). These are load-bearing; every fix in this session's history cites one of them.
2. **`.scratch/fullstack-langgraph/map.md`** — the actual project log. Every session's work is recorded there chronologically, each entry explaining what was found, why, and what was fixed, with verification notes. **This is the authoritative history** — trust it over any summary here if they ever disagree. It's ~900 lines; read the tail (most recent ~300 lines) for full context on the current state, older entries for how earlier architecture decisions were reached.
3. **`.scratch/fullstack-langgraph/issues/*.md`** — one file per named ticket (numbered 01–28), each with a `Status:` line at the top. Read a ticket's file before touching its area — the "Decisions" section in each records questions already argued out, so you don't re-litigate them.
4. **`README.md`** — how to run the app day-to-day (dev servers, env vars, test commands). Written for a human developer, not for architecture context.

## How to verify the repo right now

```bash
# Frontend
npm install
npx tsc -b --noEmit          # must be clean
npm test                      # Vitest — should show 301 passing (27 files), as of this handover

# Backend
cd backend
pip install -e .
python -m pytest -q           # should show 229 passing, as of this handover
```

Both counts will have grown by the time you read this if any prior session's work landed — treat a **lower** count than stated here as a real regression to investigate immediately, not a stale number to ignore.

To run the app live:

```bash
# Terminal 1
npm run dev                   # http://localhost:5273

# Terminal 2
cd backend
PYTHONPATH=backend:workflows/chinook-nl-to-sql uvicorn dyflow.api.main:app --port 8000 --app-dir backend
```

The canvas preview (local "Run" button) works with zero credentials via the Mock provider. The Chat panel and "Manage Workflows" save/load need the backend running. The backend itself defaults to **Ollama cloud** with zero configuration — see CLAUDE.md's "Ollama means Ollama cloud, never a local model" section; never benchmark against a local model and treat the result as representative.

## Current state, honestly

As of this handover: **229 pytest + 301 Vitest passing, `tsc` clean.** The flagship demo workflow (`workflows/intent-routed-demo/workflow.json` — router → per-intent agent/grader loops, plus a dataquery branch through an orchestrator/worker/Chinook-SQL fan-out) runs cleanly end-to-end through the real backend across all four of its branches, verified live and pinned by `backend/tests/test_intent_routed_demo_file.py` (loads the real saved file from disk, not a hand-built fixture — this is deliberate, see the "Real-file E2E suite" entry in map.md for why the hand-built fixtures alone missed a real bug).

Its diagnostics panel shows **1 error-severity entry** (the red badge count) plus **11 informational warnings** — all expected, none a bug:
- The 1 error is "Text Input: Enter a prompt for the agent" — the seeded entry field starts empty, which is expected before a user has typed a question.
- The 11 warnings are "X can loop back before continuing — valid for the backend, but the canvas preview can't run it", one per node in the intentional grader-revise loops. These are real cycles, correct for the LangGraph backend, just unrunnable by the local DAG-only canvas preview (clicking the canvas "Run" button on this file shows a toast explaining exactly that — use Chat instead).

If the red error badge ever reads higher than 1 on this specific file with no clear new cause, treat it as a regression — map.md's "13 diagnostics" and "real cause" entries document the two real bugs (a router slug bug, and an overly-blunt cycle-severity rule) that used to inflate this count, both fixed.

### A pattern worth knowing before you start: the reducer hazard

Three separate bugs this session were the exact same shape: a bare scalar field in `RunState` (`answer`, then `attempts`, then `feedback`) written by more than one node type, causing LangGraph's `InvalidUpdateError` under a fan-out or a revise loop. CLAUDE.md has a standing rule for this ("A state key more than one node type can write needs a named reducer"). If you add a new field to `RunState` (`backend/dyflow/compile/node_runtime.py`) that more than one node factory writes, give it a named reducer (`keep_latest_nonempty`, `keep_max`, or a new one) immediately — don't wait for it to crash in a real graph shape first. The three existing fixes are right next to `RunState`'s definition and are the templates to copy.

### Another pattern worth knowing: TS-schema-vs-Python-factory drift

Several bugs this session (`FormatReportNode`'s `reportTitle`/`title` key mismatch, per-node model selection, Router's `tier`) were a node's TypeScript field schema (`src/nodes/*/`) declaring a field that its Python factory (`node_runtime.py`) either read under the wrong key or never read at all — silently inert, no error, no test failure, until someone actually configured that field and got surprised. There is no automated check for this drift. If you add or rename a field on either side, grep the other side for the exact key name before considering it done.

## What's resolved (don't re-attempt)

Everything in `.scratch/fullstack-langgraph/issues/` marked `Status: resolved`. Notably, as of this handover:
- **Ticket 16** (filesystem sync) — both directions built: the editor writes files, and now also notices when a file changes externally (`src/app/workflowFileWatch.ts`), polling and diffing `savedAt`, notify-only (never auto-reload/merge, by deliberate design).
- **Ticket 17** (god classes) — `WorkflowController` is fixed at 10 public members. `WorkflowModel` is a **deliberate, recorded exception** — its internals are split (`AdjacencyIndex`, `GraphQueries`), but its own flat public method count was kept on purpose after ticket 17's own analysis concluded that flattening it the same way would be a 100+-call-site rename for a smaller-but-not-clearer surface. **Do not attempt this refactor without new evidence that changes that calculus** — re-read ticket 17's resolution note first.
- **Ticket 25** (splice-insert) — dropping a palette node onto an existing edge now inserts it inline, one undo step, type-checked before creation. `SpliceInsertCommand` (`src/core/commands/edgeCommands.ts`), `EdgeEditor.insertOnEdge`, `closestEdgeToPoint` (`src/core/model/topology.ts`).
- **Ticket 27** (kitchen-sink workflow) — the intent-routed demo itself, fully working, is this ticket's deliverable.
- **Ticket 18** (capability discovery), for tool capabilities — a workflow's discovered `tools/` capabilities register as real, connectable palette node types (`DiscoveredToolNode.ts`, `registerDiscoveredCapabilities`), and the palette now auto-updates when a new tool file appears on disk (`decideCapabilityRefresh` in `workflowFileWatch.ts` — polling, not SSE, reusing ticket 16's existing poll loop; same user-visible outcome as the ticket's own SSE sketch, no new backend wiring). Verified live both ways: against `chinook-nl-to-sql`'s three real tools, and by dropping a brand-new tool file into an open workflow's `tools/` folder with zero manual reload. What's still open, by the ticket's own drawn boundary: true node-*class* discovery for a hand-written `Final*` type outside the `BaseTool` ladder — a genuinely separate, larger question.
- **Per-node retry/timeout override UI** — `maxRetries`/`timeoutSeconds` fields, declared once in `ModelRegistry.defineNode` and inherited by every executable node type, surface in the Inspector and reach `add_node(retry_policy=, timeout=)` on the backend (`workflow_compiler.py`'s `_node_overrides`). Verified live end to end, including a backend integration test proving the override is actually applied (invocation-count assertion), not just parsed.

## What's genuinely still open, roughly by priority

Every P1 item that was *code-shaped* is now done. What remains needs a design decision before more code is meaningful — don't start implementing either of these without first pinning down the actual UX/architecture question, the way `feature-design` or a similar interview would:

- **Human-in-the-loop**: how `interrupt()`/`HumanInTheLoopMiddleware` surfaces as a canvas affordance. Not specified at all — what does the canvas show while a run is paused? Does the user respond from the chat panel, the node card, or a dedicated modal? Does the paused state survive a page reload (it should, since LangGraph checkpoints it)?
- **Streaming/observability enhancements**: token streams and per-node traces already flow to the chat panel (ticket 27); a live LangSmith-style trace view or deeper per-node observability on the canvas itself is unbuilt and unspecified — what would it show that the chat panel's activity feed doesn't already?

**P2 — decided against or deferred with a recorded reason, don't just "finish" them without re-reading the ticket:**
- **Ticket 20** (cardinality-fields) — decision recorded: the generic field-schema primitive stays unbuilt because every motivating example was solved a different way (ports and composition). Don't build it speculatively.
- **Ticket 21** (authored-text-storage) — decision recorded, implementation deliberately deferred. Read before touching how prompts are stored in `workflow.json`.
- **Sandboxing capability discovery** — importing user code is acceptable for a local dev tool; unresolved for hosted use. Only becomes actionable if hosting comes into scope.
- Migration of pre-schema-generation v1 workflow JSON, multi-user/auth, evaluation/tracing (LangSmith) — all listed in map.md's "Not yet specified" section as plausible future work with no current design.

**Explicitly out of scope — do not build these:**
- Real-time collaborative editing (two people on one canvas). See map.md's "Out of scope" section for the full reasoning (git-as-sync-mechanism, no CRDT, Postgres Realtime kept only for live *viewing*, not co-editing).
- Deployment/hosting/infrastructure.
- Replacing JointJS core with another canvas library.

## Working conventions to keep following

- **TDD.** Write the failing test first, especially for anything touching `core/` (pure TypeScript, directly unit-testable — CLAUDE.md: "there is no excuse for untested logic there").
- **Never refactor a god class without tests in place first** (CLAUDE.md, and see ticket 17's own history for why this matters in practice).
- **Verify live, not just green tests.** Several real bugs this session (the router slug bug, the chat-panel layout bug, the "Run" button silent failure) were invisible to the full test suite and only found by actually loading the app in a browser and clicking through it. `npx tsc -b --noEmit` and a green test suite are necessary, not sufficient.
- **LangGraph facts come only from the `docs-langchain` MCP server**, never from memory or invented. If that MCP server isn't available in your environment, say so explicitly rather than guessing at LangGraph semantics.
- **Ollama cloud, never local**, for any benchmark, demo, or default — see CLAUDE.md for the specific documented incident that makes this a hard rule, not a preference.
- Commit messages in this repo's history explain *why*, with the failure scenario that motivated the fix, not just *what* changed — match that style; it's what let this handover be written from `git log` and `map.md` alone.
- After any fix, update `.scratch/fullstack-langgraph/map.md` with a dated entry (the existing entries are the format to follow) — that file is what makes a handover like this one possible at all.
