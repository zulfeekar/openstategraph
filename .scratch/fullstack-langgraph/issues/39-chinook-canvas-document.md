Type: task
Status: resolved
Blocked by: 33

## Question

`chinook-nl-to-sql` — the flagship — has `agents.py`/`graph.py`/`tools/` and
**no `workflow.json`**, so it is invisible to `WorkflowStore.list()` and
cannot be opened on the canvas. Two API endpoints are hardcoded to its slug.

Author its canvas document: router → ReAct agent + the three SQL tools →
grader with the revise loop, matching what `graph.py` hand-builds; verify
the compiled graph and the hand-built one produce the same Mermaid; keep
`graph.py` as the "compiler output is just Python" demonstration or retire
it explicitly. De-hardcode `/api/workflows/chinook-nl-to-sql/*` endpoints
(moves with ticket 49).

## Answer

Resolved (2026-08-07). `workflows/chinook-nl-to-sql/workflow.json` now exists
in the same envelope form as `tabular-analytics` (`{version, name, savedAt,
document}`), and the flagship appears in `WorkflowStore.list()` and loads on
the canvas.

**The shape** (settled with the user — no classifier router; the loop *is*
the demonstration):

```
in1 (input.text) → agent-sql (agent.llm, tier react, SQL-directive
systemPrompt) ← tool bus: tool-tables / tool-schema / tool-sql
agent-sql.result → grader-sql (route.grader, criteria mirroring graph.py's
grade() checks, criteriaMode replace, maxAttempts 3)
grader-sql.pass → out1 (output.formatted); grader-sql.revise →
agent-sql.feedback  — the typed-feedback cycle, drawable because the port
types allow it and nothing else.
```

`in1` carries a default prompt (clears the "Enter a prompt for the agent"
diagnostic; Chat's question overrides it per run — `_input` prefers
`state["question"]`). `tool-sql` sets `maxRows: 200`, exercised end-to-end by
`ExecuteSqlTool.configure()`.

**Versus `graph.py`:** the compiled document produces the same
evaluator-optimizer topology — `in → agent → grade → {revise: agent, pass:
out} → END` against graph.py's `orient → write_sql → grade → {revise:
write_sql, synthesise} → END`. Node-for-node identical Mermaid is not
achievable nor desirable: `orient` (deterministic table listing) is subsumed
by the bound `chinook_list_tables` tool, and the deep-agent `synthesise` tier
by the agent's own final message + `output.formatted`. **`graph.py` is kept**,
explicitly, as the "compiler output is just Python" demonstration — it also
still documents the three-tier point (LangGraph node / create_agent /
create_deep_agent) that the minimal canvas document deliberately does not
re-enact.

**Tests** — `backend/tests/test_chinook_demo_file.py`, the real-file E2E in
the mould of `test_intent_routed_demo_file.py` (loads the artifact from disk,
scripted `RespondingModel`, all paths):
- plan has no compiler warnings;
- all three Chinook tools survive serialization → `plan.tool_bindings` →
  `runtime.last_bound_tools`;
- the grader declares both `pass` and `revise` conditional destinations;
- pass path: answer reaches `out1`, `attempts == 1`;
- revise path: first FAIL loops back and **the grader's reason reaches the
  agent's retry prompt** ("Your previous answer was rejected: …"), second
  attempt passes, `attempts == 2`.

5/5 pass; the 8 failures elsewhere in the suite pre-exist on a clean tree
(verified by stash) and belong to concurrent ticket-37/43 work.

**Live verification** (the part a scripted model cannot give): loaded via
Manage workflows → Load in the running editor — all 7 nodes render, the
workflow-scoped Chinook types register on load, diagnostics show only the two
expected "can loop back" cycle notes. Asked through Chat: *"Which artist has
the most albums, and how many?"* → the agent called the real tools
(list-tables output visible in the stream), wrote
`SELECT ar.Name, COUNT(a.AlbumId) … GROUP BY … ORDER BY AlbumCount DESC`,
grader passed, Formatted Output rendered: **Iron Maiden, 21 albums** —
correct against the database.

**Explicitly deferred, as charted:** the two hardcoded
`/api/workflows/chinook-nl-to-sql/{graph,ask}` endpoints move with
[ticket 49](49-workflow-package-contract.md); nothing here entrenches them
further (the document runs through the generic `/api/runs/stream` path, which
is what Chat uses).
