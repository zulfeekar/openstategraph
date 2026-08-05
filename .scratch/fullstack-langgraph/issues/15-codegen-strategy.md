Type: research
Status: resolved
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

---

## Answer: **(c) Both — interpret to execute, generate as a one-way export**

Judged against the three questions the ticket itself set, which is what decides it:

**Does a stale `graph.py` ever get executed?** Under (b), yes — and that is the
whole risk. Under (c), **never**, because the generated file is not imported by
anything. Staleness is only dangerous when the stale artifact is on the execution
path; take it off that path and the risk disappears rather than being managed.

**Can a user hand-edit and keep it?** No, and that must be stated plainly rather
than implied. The export is regenerated and overwritten. Hand-written code belongs
in `tools/` and `functions/`, which are user-owned and referenced *by name* from
the document — that is where extension actually happens, and it already works.
Pretending `graph.py` is editable is how these systems earn their reputation.

**What does `git diff` look like after moving one node?** **Empty** — and this is a
requirement on the generator, not a happy accident: geometry must not reach the
emitted code. Position and size live in `workflow.json` only. A generator that
serialised layout would make every drag a code diff, and the export would be
worthless for review.

Rejected (a) interpret-only because the user explicitly asked to see code, and
"you can't" is a worse answer than "here it is, read-only". Rejected (b)
generate-only because it buys a build step and a staleness class of bug for an
artifact nobody needs on the hot path.

## Built: the interpreter (`backend/dyflow/compile/workflow_compiler.py`, 24 tests)

The load-bearing half. `plan()` produces an inspectable `CompiledPlan`; `build()`
turns it into a `StateGraph`. The plan is deliberately separate so the future
generator consumes **the same plan** — that makes interpreter/generator agreement
true by construction rather than by discipline.

### The finding that mattered: not every edge is a graph edge

| Target port | Meaning | Compiles to |
| --- | --- | --- |
| `tool` | available to that agent | a **binding** — no graph node, no edge |
| `skill` | shapes the prompt | a **binding** |
| `text`, `result` | control flow | `add_edge` |
| `feedback` | grader rejection | part of a **conditional** edge |

A tool node is **not a step**. Sequencing one would run it on its own *and* let the
agent call it — the same work twice, with a plausible-looking result.

### Two bugs found only by compiling a real canvas export

Every hand-written fixture used tidy ids like `ag1` and wired only what its test
was about. A document exported from the actual editor found both immediately:

1. **LangGraph reserves `:` in node names.** Our ids are `node:agent.llm-1`, so
   `add_node` raised outright. Now sanitised by `safe_name`, derived from the *id*
   rather than the label because LangGraph treats a node name as identity and a
   rename would break an interrupted thread (ticket 04).
2. **A bound tool became an entry node.** I had excluded it from `exits` but not
   from `nodes`, so it had no incoming edge, was treated as an entry, and got
   wired from `START` — reintroducing the exact doubling the binding distinction
   exists to prevent. **The unit tests passed while this was live**, because they
   only asserted `exits`. A bound node is now not a graph node at all, unless it
   also takes part in control flow.

The lesson is the reusable part: fixtures agree with the code that produced them.
A real export is the only thing that disagrees.

### Verified

A canvas document containing input → router → agent (+ bound tool) → grader, with
the grader's `revise` looping back, compiles to the correct graph: labelled
conditional edges for both the router branch and the grader's pass/revise, the
loop intact, the tool absent from the topology, `START`/`END` wired to the right
nodes, and no warnings.

## Known duplication, deliberately visible

`DEFAULT_PORT_SPECS` mirrors port types from the TypeScript catalogue, which
CLAUDE.md forbids. It is marked as temporary and the resolver is **injectable**, so
generated output can replace it without touching the compiler — and a test asserts
the compiler goes through the injection point, so the seam cannot rot shut. Ticket
02 owns the generation. Until then an unknown node type compiles as an opaque node
with control-flow edges: wrong in the safe direction, since a spurious edge is
visible in the Mermaid preview whereas a missing one silently drops a step.

## Not done

The **generator** itself. The plan exists and is the right input for it; emitting
deterministic, readable Python from it is the remaining half, plus the property
test that generated code and interpreted graph produce identical Mermaid.
