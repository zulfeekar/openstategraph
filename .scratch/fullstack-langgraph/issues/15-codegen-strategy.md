Type: research
Status: open
Blocked by: 03, 06

## Question

Establish how — and whether — to generate Python code from an authored workflow, and how far "bidirectional" can honestly go.

The user asks whether the visual workflow saves *as generated code*, e.g. `workflows/text-to-sql-workflow/{generated code}`.

Research, from primary sources and prior art:
- **Prior art in this exact space.** How do n8n, Node-RED, Prefect, Dagster, Flowise, and Langflow persist a visually-authored flow — as data (JSON/YAML) interpreted at runtime, or as generated source? Which of them attempt round-trip (edit the code, see the diagram update), and what is reported to go wrong?
- **The generated/user-owned split.** How do Prisma, protobuf/gRPC, OpenAPI generators, and Alembic separate regenerated files from hand-written ones? Directory separation versus in-file markers — which survives contact with users?
- **Generation mechanics.** Template-based emission versus building a Python AST (`ast` / `libcst`). Which gives readable, diffable, deterministic output? Determinism matters: regeneration must produce a byte-identical file when nothing changed, or every save is a spurious diff.
- **Round-trip feasibility.** What is actually required to parse hand-edited Python back into a graph model, and where does information get lost (comments, formatting, code the canvas cannot represent)?

Deliverable: a recommendation on (a) data-as-truth versus code-as-truth, (b) whether round-trip is worth attempting at all, and (c) the concrete directory layout for `workflows/<slug>/`. Be blunt about what will not work.

---

## Reframed after 04, 05 and 07 resolved

The earlier framing implied codegen was forced. It is not — two findings interact:

- **04/05** established that LangGraph has no serialisable graph format, and that Agent Server discovers graphs as Python modules registered in `langgraph.json`. Read alone, that makes emitting `.py` files mandatory.
- **07** then ruled Agent Server out on licence (ELv2). With our own FastAPI on MIT `langgraph`, we can construct a `StateGraph` **programmatically in memory** from stored JSON. `langgraph.json` is Agent Server config and no longer applies.

So there are genuinely two viable designs, and this ticket must choose:

- **(a) Interpret.** `workflow.json` → `StateGraph` built at runtime. No emitted files, no staleness, no drift, nothing to keep in sync. But the user never sees code, and cannot hand-extend a workflow beyond the tool files.
- **(b) Generate.** `workflow.json` → a committed `graph.py`, imported and executed. Gives real, readable, diffable, version-controlled code — which is what the user actually asked for — at the cost of a build step and a staleness risk.
- **(c) Both.** Interpret as the execution path; generate as a one-way *export* the user can read, diff and vendor out. This gets the artifact without making it load-bearing.

Evaluate all three against: does a stale `graph.py` ever get executed? can a user hand-edit and keep it? what does `git diff` look like after moving one node? Recommend one.
