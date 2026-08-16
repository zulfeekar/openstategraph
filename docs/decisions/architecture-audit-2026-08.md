# Architecture audit — 2026-08

Scope: `backend/openstategraph/compile/**`, `backend/openstategraph/abc/**`,
and the agentic design (prompt composition, middleware slot table, state
schema/reducers, subgraph mounting, `Send` fan-out, HITL, memory/knowledge).
LangGraph/LangChain facts verified against the docs-langchain MCP server on
the audit date. Regression pins: `backend/tests/test_architecture_audit_2026_08.py`.

## Found and FIXED

### 1. Turn-boundary RESET missed the fan-out channels (state soundness)

`_input` reset `outputs`/`decisions`/`answer`/`feedback`/`attempts` but not
`subtasks` or `worker_results`. Mechanism of the latent bug: a checkpointed
thread's second turn re-plans from `attempts=0`, so `BaseOrchestrator.plan`
issues the same ids (`task-1`, `task-2`, …) as the first turn's first plan.
If a turn-2 worker died before writing, `_format_report_function` would find
turn 1's stale result under the identical key and silently blend it into the
new report — the exact failure class the generation-prefixed ids were built to
prevent *within* a run, reintroduced *across* runs. Stale `subtasks` from a
prior turn's orchestrator also inflated `current_ids`, rendering phantom
"failed before reporting" sections. Fixed: `_input` now emits
`{"subtasks": {RESET: ""}, "worker_results": {RESET: ""}}`; `merge_decisions`
already understood the marker.

### 2. Orchestrator trusted stale feedback (reducer-semantics drift)

`feedback` is `keep_latest_nonempty` — by design, a grader's later `""`-on-pass
can never clear a rejection. `_agent` therefore gates feedback on "does the
deciding node's revise/rejected edge target me AND is its latest decision
still that label"; `_orchestrator` read `state["feedback"]` raw. So a passed
grader's old rejection, or a *different branch's* approval rejection, was
appended to every replanned subtask as if live. Fixed: the same
`feedback_sources` gate, verbatim, in `_orchestrator`.

### 3. Worker ignored its per-node model override (contract drift)

`_resolve_model`'s own docstring records this bug class (canvas shows a
per-node model select; backend runs the graph default). `_worker` used
`self.model` directly. Fixed: `_worker` resolves through
`self._resolve_model(node["data"])` like agent/router/grader/orchestrator.

### 4. Worker bypassed SystemPrompt composition for skills context

`_worker` concatenated `skills_context` into the `rules` string. CLAUDE.md's
prompt rule: generated context rides *above* rules via `SystemPrompt`, and only
`SystemPrompt.render()` decides order (contract last). Fixed: the worker now
passes `context=self.skills_context, rules=<skill-or-default directive>` to
`ReactAgentNode` — same shape as `_agent`.

### 5. `question` channel pinned as single-writer

`question: str` has no reducer, which is legal only while no *node* writes it
(it arrives from the caller's invoke and the subgraph mount's explicit input
mapping). A source-level pin now fails the moment a node update grows a
`"question":` key, forcing the CLAUDE.md named-reducer rule to be applied then.

## Verified — NO drift (against docs-langchain)

- **Middleware slot table vs hook semantics.** Docs confirm: `before_*`
  first→last, `after_*` last→first, `wrap_*` nested with the first middleware
  outermost. A single list position genuinely means three things at once, so
  the name-keyed `MiddlewareSlotTable` with a base-owned canonical order and
  last-moment `flatten()` into `create_agent(middleware=[...])` is the correct
  seam. No raw priority numbers are exposed anywhere.
- **Prompt composition order.** Router, Grader, Orchestrator (both the plan
  and the label prompts), agent tiers, the advisor block, and the grader's
  rubric/question blocks all flow through `SystemPrompt`; `render()` is the
  only place order is decided and the output contract is appended last in
  every family. The rubric and question ride as *context* so
  `replace_defaults` cannot reach them.
- **Reducers as a named enum.** `add_messages`, `merge_decisions`, `keep_max`,
  `keep_latest_nonempty` — all named functions, no ad-hoc lambdas anywhere in
  the schema.
- **Compile seam one-directional.** Nothing reads runtime objects back into
  the document/model. The subgraph mount's `get_config()` read is run-time
  config plumbing (and filters LangGraph's dunder/checkpoint keys), not a seam
  violation.
- **Vocabulary.** `workflow.json` and the plan speak port/edge/binding
  vocabulary; no LangGraph type names leak into it or into `core/`.
- **`Send` payload shape.** Docs and the code agree the payload *replaces*
  what the dispatched node sees; workers read only `task_id`/
  `task_instruction` and the orchestrator must pack anything else explicitly.
- **HITL discipline.** `interrupt()` is called exactly once, unconditionally,
  per `human.approval` invocation; resume via `Command(resume=...)`;
  checkpointer required — all per current docs.
- **Retry/timeout as graph assembly.** `set_node_defaults(retry_policy,
  error_handler)` with per-node `add_node` overrides (docs: per-node wins) and
  a `<1.2` per-node fallback. The `error: NodeError` annotation contract is
  documented in-code and test-pinned.
- **Advisor/knowledge context token costs.** The advisor catalogue is a
  prefix-filtered registry listing (one line per suggestible tool — bounded by
  the registry, currently a handful of entries). Knowledge is deliberately
  on-demand (`knowledge_lookup` tool) rather than prompt-stuffed, so its
  catalog cost is one tool round-trip, not per-prompt. `_thread_question`
  history is bounded to 6 turns. No unbounded context block found.

## Deferred (with reasons)

- **`cache_policy` / `compile(cache=...)`.** Available (docs: `CachePolicy`
  on `add_node`, `InMemoryCache` at compile). Deliberately unused: the
  model-driven nodes are non-deterministic and thread-stateful, so caching
  them is wrong; the deterministic `function.*` nodes are cheap. Revisit if a
  discovered function ever becomes expensive — it would be a
  `_node_overrides`-style graph-assembly parameter, never a node concern.
- **Per-`Send` `timeout=TimeoutPolicy(...)`.** Docs allow tightening a
  worker's timeout per dispatched task. No card expresses a per-subtask
  timeout today; adding the plumbing without a UI field is speculative.
- **Parallel-interrupt resume maps.** Docs describe resuming multiple
  simultaneous interrupts by `{interrupt_id: value}`. Our shapes run one
  `human.approval` at a time; two approvals in parallel branches would need
  the map. Defer until the canvas can express that shape; the API layer is
  where it lands.
- **Durability modes (`sync`/`async`/`exit`).** A server-run concern
  (`backend/openstategraph/api`), not a compile concern; current default
  (`async`) is acceptable for editor runs. Note for the eventual deploy story.
- **`maxConnections: Infinity`** (ticket 08) — pre-existing, tracked there.

## node_runtime split — PLANNED, not executed

`node_runtime.py` was ~1.5k lines when this was measured (2026-08-09); it is
well past twice that now — `wc -l` is the number, and `gap-register.md` RC-07
records why chasing it through prose was abandoned. Judged against the
god-class rule it is
*borderline rather than violating*: `NodeRuntime`'s public surface is small
(`factory`, the unresolved-\* warning lists, and the injected collaborators);
the bulk is per-family private builders registered in one `_builders` table,
plus module helpers. The mass is real, though, and the seams are clean:

1. `compile/state.py` — `RESET`, the three reducers, `RunState`. Pure, no
   imports from the rest of the file.
2. `compile/context.py` — `_thread_question`, `_final_text`, `_upstream_text`,
   `_text`, `advisor_context` (prompt/state text helpers).
3. `compile/nodes/` package, one module per family, each exporting a
   `build(runtime, node_id, node, plan)` function: `io.py` (input/output/
   passthrough), `agents.py` (`_agent`), `deciders.py` (router/grader/
   approval + `_DeepAgentAsChatModel`, `_branch_entries`), `fanout.py`
   (orchestrator/worker/format_report), `mounting.py` (subgraph +
   `apply_mount_overrides`, `PackageAssets`), `functions.py` (discovered
   functions).
4. `node_runtime.py` keeps `NodeRuntime` (the `_builders` table becomes a
   registry of those functions bound to `self`) and **re-exports every name
   currently importable** (`RESET`, `RunState`, reducers, `_thread_question`,
   `apply_mount_overrides`, `PackageAssets`, `RuntimeServices`,
   `ToolRegistry`, `chinook_tool_registry`, …) so the test surface —
   which imports from `node_runtime` heavily, including underscore names —
   never moves.

Why not executed now: the builders are closures over `NodeRuntime` state
(`_types`, `_nodes`, `_model_cache`, warning lists, the ambient-knowledge
memo), so the mechanical move rewrites every `self.` reference in ~900 lines
during the same session that changed turn-reset and feedback semantics.
Two behavioural fixes and a structural rewrite in one change set is exactly
the churn the tests-before-refactor rule exists to prevent. The split is
mechanical, the seams above are the whole design, and it should be its own
ticket with zero behavioural diffs.
