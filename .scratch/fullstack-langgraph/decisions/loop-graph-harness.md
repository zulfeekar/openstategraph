# Loop, Graph and Harness engineering — how it maps onto Dyflow

**Source material:** a DevCompass deck (`harness-loop-graph.pdf`, shared by the
user) plus their two-part "Loop Engineering vs Graph Engineering" articles, and
an independent findings table the user supplied (symptom → likely fix, a
production-readiness checklist, and a list of "expensive mistakes"). Read in
full before writing this.

## The three-layer framework, as given

```
HARNESS = ENVIRONMENT   (tools, files, memory, permissions, sandboxes, traces)
LOOP    = FEEDBACK      (produce → check against evidence → retry with a reason → stop)
GRAPH   = FLOW          (nodes, edges, branches, joins, cycles, exits — explicit control flow)
```

Load-bearing quotes worth keeping verbatim, because they are decision rules, not
just framing:

- *"A model decides. A harness lets it act. A loop makes it prove the result. A
  graph controls what is allowed to happen next."*
- *"Do not loop on confidence. Loop on evidence. 'The agent says it is
  finished' is not proof."*
- *"An unbounded retry is not reliability. It is a cost leak. Every loop needs
  a measurable objective, fresh evidence, maximum attempts, and a named
  escalation path."*
- *"Trace first. Formalize second."* — do not convert an imagined process into
  forty nodes before watching a capable agent do the work.
- *"State schema — what each node may read or update and how parallel results
  are merged"* is named explicitly as a **graph-engineering decision**, not an
  implementation detail.

The nesting matters: **the graph runs inside the harness. The loops run inside
parts of the graph.** They are not competing designs — a system that gets one
layer right and starves another still fails, in a specific and diagnosable way
(their own symptom table: "cannot access the right tool" → harness; "close but
unreliable" → loop; "specialists must run in order" → graph).

## Where this session had already independently arrived at the same design

This is worth stating plainly: nothing in the shared material contradicted
architecture already built over prior sessions. It **confirms and names** three
things that existed under different labels:

| DevCompass term | Already built as |
| --- | --- |
| Harness | `WorkflowCompiler` + `NodeRuntime` + FastAPI seam + real Chinook tools (read-only driver, not string-matched) |
| Loop | `BaseRouter` / `BaseGrader` — evidence-checked, bounded (`maxAttempts`), feedback-carrying, terminate-with-honesty on exhaustion |
| Graph | `add_conditional_edges` for router/grader; **`Send` fan-out + reducer join** for the orchestrator (this session's addition) |

The one thing the material sharpened rather than merely confirmed:
**"the state schema and how parallel results are merged" is graph engineering,
not an afterthought** — and this session found a real, live bug that is exactly
that class of oversight (below).

## What this session added: the orchestrator, and the fan-out/join primitive

`IOrchestrator → BaseOrchestrator → Orchestrator` (`backend/dyflow/abc/orchestrator.py`,
16 tests). Same ladder as Router and Grader, for the same reason: turning an
instruction into subtasks is mechanical (bound the count, mint an id, never
produce zero), and only the *decomposition rule* is a legitimate extension
point. The default is **deterministic** — split on numbered lists, semicolons,
"and" — rather than model-driven, which is the checklist's own instruction:
*"keep control model-driven only where a rule cannot express the decision"*,
and decomposing a punctuated instruction is exactly a rule's job.

The graph-engineering half: `WorkflowCompiler` now recognises a `worker`-typed
port as a **fan-out declaration**, distinct from control flow and from a
tool/skill binding — a third category alongside the two the compiler already
knew. It compiles to `add_conditional_edges` returning a list of `langgraph.types.Send`,
verified against the installed LangGraph directly before writing any product
code (`Send` payload **replaces**, not merges, the dispatched node's visible
state — checked, not assumed).

## Bugs found only by combining the two mechanisms and running for real

Every one of these was invisible to hand-written fixtures and surfaced only
when a loop's revise edge re-entered a fan-out/join subgraph, or when a real
model actually exercised the tool-bound path. This is the checklist's own
warning about self-review and "trace first" made concrete: a system that only
tests its happy path with scripted models does not find these.

1. **`answer` was a bare scalar field with three legitimate writers**
   (`_agent`, `_format_report_function`, `_output`). It looked safe in every
   scripted test because none of them happened to write it in the same
   superstep — until a real run (router + orchestrator + two tool-bound
   workers) did, and LangGraph raised `InvalidUpdateError`. Fixed with a named
   reducer (`keep_latest_nonempty`), reproduced deterministically in
   `test_answer_channel_concurrency.py` without needing a model or a tool.
   This is precisely the "state schema — how parallel results are merged"
   graph-engineering decision the material calls out.

2. **Subtask ids collided across replans.** `Orchestrator.plan()` always
   numbered from `task-1`. A revise loop's second planning pass reused the
   same ids as the rejected first pass, silently aliasing fresh results onto
   stale ones in the shared `worker_results` dict. Fixed by folding the
   attempt count into every id (`task-{generation}-{n}`), and by scoping the
   report's join to only the ids the *current* plan declared — discarding
   stale entries from a rejected attempt rather than blending them in.

3. **A worker with tools but no system prompt answered from parametric
   knowledge.** Chinook tools were correctly bound and resolvable
   (`unresolved_tools` was empty), but a bare tool-bound `create_agent()`
   given only a one-line human instruction did not reliably choose to call
   them — for a capable-but-not-directed model, a vague "use your tools" nudge
   loses to confident training-data recall. Partially mitigated with a
   directive default prompt naming the exact call sequence, mirroring the
   proven-successful Chinook skill text from the standalone-agent path. **Not
   fully resolved as of this writing** — see below.

## What is proven deterministically, and what is not, and why that split is honest

**Proven, by 182 passing pytest, with no model and no API key:**
`Send` really dispatches once per planned subtask · every dispatched
instance's result reaches the join under its own key · a revise edge really
re-enters the fan-out/join subgraph rather than resuming after it · the
attempt cap really terminates the loop even while re-doing branching and
joining each lap · the feedback reason really reaches the replanned
instruction · ids never collide across attempts · the answer channel resolves
two same-tick writers without raising.

**Not, and cannot be, proven by a unit test:** that a *particular* model
reliably chooses to call a *particular* tool given a *particular* prompt. Two
live runs against `ollama:gpt-oss:120b-cloud` (cloud, per the standing
instruction never to use a local model) showed the wiring completing
correctly end to end while the model itself answered from general knowledge
rather than the database on two of three dispatched subtasks. This is a
**model/prompt-engineering finding**, not a wiring defect — exactly the
distinction this project's own ticket 15/28 notes already draw ("whether a
model writes good SQL is a model evaluation, not a unit test"), and conflating
the two would be the "blaming the model for orchestration failures" mistake
the checklist explicitly warns against — except here it is the *opposite*
direction worth guarding against too: not blaming a real prompting gap on
"orchestration" once the orchestration is independently proven correct.

## Standing rule, added to CLAUDE.md

**A state key more than one node type can write must use a named reducer, never
a bare scalar or `LastValue` field.** `decisions`, `outputs`, `subtasks` and
`worker_results` already followed this; `answer` did not, and that gap was
latent until a real graph exercised it. Applies to every future compiled
workflow state schema, not just this one.

## Resolved after further investigation: the worker's tools were never bound

The "tool-use reliability" finding above turned out not to be a model or
prompting problem at all — it was a second, more basic wiring bug, and
finding it required treating the earlier truncated live result as unresolved
rather than as an accepted limitation of the model.

**`WORKER_TYPE`'s entry in `WorkflowCompiler.DEFAULT_PORT_SPECS` never declared
a `tools` or `skill` port.** Only `dispatch` and `result` were listed. An edge
into either port therefore fell through `default_port_resolver`'s "unknown
port" fallback and was classified as ordinary control flow rather than a
binding — so `plan.tool_bindings` never saw it, `_worker`'s `lc_tools` came
back empty regardless of what was wired on the canvas, `default_prompt` fell
back to `""` (its ternary is `if lc_tools else ""`), and the model received
no tools and no directive, and answered from parametric knowledge with
nothing to ground it. This is exactly the same shape of bug as the
`answer`-channel collision and the id-collision bug above: correct in every
scripted fixture, because no fixture happened to wire a tool onto a worker
and assert on the binding — `test_a_tool_is_bound_not_sequenced` covered the
**agent's** identically-named `tools`/`skill` ports, and nothing covered the
worker's.

Fixed by adding both entries to `WORKER_TYPE`'s port spec table
(`backend/dyflow/compile/workflow_compiler.py`), with a regression test
mirroring the agent's own (`test_a_tool_bound_to_a_worker_is_bound_not_sequenced`,
`backend/tests/test_workflow_compiler.py`) proving the binding is registered
and the edge is excluded from `plan.edges`.

Separately, `_worker` was also changed to pass its prompt as
`create_agent(system_prompt=...)`, matching `workflows/chinook-nl-to-sql/agents.py`'s
proven `build_sql_agent` shape, rather than prepending a `SystemMessage` to
the per-invocation `messages` list on an agent built with no `system_prompt`
at construction. This did not turn out to be the load-bearing fix — the port
spec gap was — but it removes a real difference from the one place this exact
directive-prompt style was already known to work, and costs rebuilding the
agent once per dispatched task rather than once per compile, which is
negligible next to an LLM call.

**Verified live, twice, after the port-spec fix**, against
`ollama:gpt-oss:120b-cloud` with real Chinook tools bound to a worker node:
correct answers ("top genre by revenue" → Rock, $826.65; "which genre has
the most tracks" → Rock, 1,297 tracks) produced by the exact tool sequence
the prompt asks for — `chinook_list_tables` → `chinook_get_table_schema` (as
needed) → `chinook_execute_sql` with a correct joined, grouped, sorted,
limited query — inspected directly via each message's `tool_calls` and
`ToolMessage` content, not inferred from the final answer's plausibility.
Two other live attempts failed with Ollama cloud's own transient `500`/`-1`
`ResponseError`, unrelated to this fix; retrying reproduced success. This is
now closed, not merely mitigated.

## TypeScript node types — built

`OrchestratorNode.ts`, `WorkerNode.ts` and `FormatReportNode.ts`
(`src/nodes/orchestrate/`) register `orchestrate.supervisor`,
`orchestrate.worker` and `function.format_report` in the canvas catalogue,
following the same shape as `RouterNode.ts`/`GraderNode.ts`: Orchestrator and
Worker refuse to execute in the browser preview (Python owns `Send`
fan-out — ticket 07), while Format Report genuinely runs there, since joining
text needs no model and no LangGraph runtime. A new `PORT.worker` port type
was added to `vocabulary.ts`, matching the compiler's `WORKER_PORT_TYPE`; the
orchestrator's `workers` output is capped at `maxConnections: 1` because the
compiler records at most one dispatch target per orchestrator — a single
wire, not a bus, unlike the `tools` pill both the Agent and Worker nodes
carry. 13 new Vitest tests plus a fixture-registry update; 192 Vitest + 137
pytest passing, `tsc -b --noEmit` clean.

## Not done, honestly listed

- Model-driven decomposition (a `BaseOrchestrator` subclass whose `split()`
  calls a model) is a legitimate, cheap extension once wanted — not built,
  since the deterministic default covers the tested cases.
- The streaming/chat-sidebar contract from ticket 27's original shape
  (`updates` + `messages` multiplexed over one SSE connection, `subgraphs=True`)
  is still unbuilt — this session closed the graph-engineering and node-
  registration gaps, not the observability ones.
