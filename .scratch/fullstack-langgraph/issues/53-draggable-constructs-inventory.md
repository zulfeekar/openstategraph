Type: research
Status: open
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
