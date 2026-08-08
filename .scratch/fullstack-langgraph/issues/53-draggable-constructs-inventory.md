Type: research
Status: resolved (2026-08-07) — research complete
Blocked by:

## Question

An inventory, from `docs-langchain` (never memory), of every LangGraph /
LangChain / deepagents construct that could become a drag-and-drop element —
a node, an edge kind, or an assignment onto one — beyond what the palette
already has (agent tiers, router, grader, orchestrator/worker, HITL, tools,
functions, subgraph).

Candidates to confirm or refute, with the exact API each maps to: handoffs,
skills, subagents-as-cards, memory/store attachments, cache policies on an
edge or node, `Command(goto=)` dynamic edges, `add_sequence`, parallel static
branches with a join/barrier, streaming taps, evaluator patterns, deepagents'
filesystem/sandbox tools as bindable capabilities. For each: does it compile
to graph assembly (a `workflow.json` concern) or to node config (a field)?
The output feeds tickets 52 (Team members) and the palette roadmap.

## Resolution

Findings: [research/53-draggable-constructs.md](../research/53-draggable-constructs.md) — 17 constructs, docs-cited. One-liners: subagent cards are the strongest (any workflow → `CompiledSubAgent` on an agent's subagents bus — feeds ticket 52); skills + backends are clean node-config cards; `Command(goto=)` is a dashed dynamic-edge kind (never mixed with static routing from one node — free validation rule); `defer=True` is a one-boolean join badge; refuted: `add_sequence` (sugar), streaming taps (invocation-time), evaluator-optimizer (already Grader+cycle — ship as template).
