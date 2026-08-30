# Chinook Assistant

**The one visible workflow in this repository, and now the only Chinook
package.** `GET /api/workflows?surface=chat` returns this and nothing else;
everything else on disk (`concierge`, `workflow-architect`) is `hidden: true`
infrastructure. The default surface is `editor`, which lists hidden packages
too — flagged, so a developer sees what is there.

Fourteen nodes, left to right. The rule it was built to: every node must be
explainable in one line, and a diagram nobody can read has failed regardless
of what it does.

| Node | One line |
| --- | --- |
| `in1` **Question** | where the question enters |
| `router1` **Intent** | sorts the question into one of five intents and takes exactly one branch |
| `skill-sql` **SQL Analyst skill** | a Markdown skill file wired into the analyst's `skill` port — the analyst's rules live here, not on the agent |
| `agent-sql` **Data Analyst** | writes and runs the SQL. Its own prompt field is **empty**: its rules arrive over the wire |
| `tool-tables` / `tool-schema` / `tool-sql` | list tables → read schema → run one read-only `SELECT` |
| `grader-sql` **Verified?** | passes the answer on, or sends it back with a reason. Three attempts |
| `agent-chat` **Front Desk** | the only node that answers without a tool: greetings, honest refusals, general knowledge |
| `agent-web` **Web Researcher** | the only node allowed to reach the live internet |
| `t-search` / `t-fetch` | the two tools that let it: search for sources, then read one |
| `guard-web` **Cited?** | the only thing standing between the open web and the answer: no figure leaves without the URL it was read from. A package function, no model |
| `out1` **Answer** | renders whichever branch ran, as Markdown |

## Five intents, three destinations

```
data_query        ─────────────▶  Data Analyst ─▶ Verified? ─pass─▶ Answer
                                       ▲              │
                                       └──── revise ──┘
greeting          ──┐
off_topic         ──┼──────────▶  Front Desk    (one agent, no tools)
general_knowledge ──┘
web_lookup        ─────────────▶  Web Researcher ─▶ Cited?  ─pass─▶ Answer
                                  + search/fetch      │
                                       ▲              │
                                       └──── revise ──┘
```

Five intents, because those are the five things people actually send. Three
destinations, because **a router port is a destination, not a taxonomy** —
three of the intents want the same answer-shape (a short honest reply with
no tool call), and giving each its own agent would be three cards with one
prompt between them. The distinction that matters to a *reader* is on the
branch labels; the distinction that matters to the *run* is which node
answers.

The branch order is the layout: destinations sit top-to-bottom in the same
order the branches are declared. That rule survives the collapse, and it is
why the committed positions are **placed by hand rather than taken from
Arrange automatically**.

That was measured, not assumed. Both layouts were loaded into the editor and
every link path was sampled against every card's box at fit zoom, the bar
`docs/decisions/edge-legibility.md` sets:

| Layout | Card crossings |
| --- | --- |
| `Arrange automatically` | **1** — the `web_lookup` link, through four cards |
| committed (branch order) | **0** |

The layout engine ranks by graph depth, so it puts the Web Researcher on the
top rank (one hop from the router) and the analyst on the bottom (three:
agent → tools → grader) — exactly reversing the branch order, which sends the
last branch's link back across the whole diagram. Pressing **Arrange
automatically** on this document therefore makes it slightly worse, which is
worth knowing rather than discovering.

There is **no `follow_up` branch**, and that is a finding rather than an
omission. The follow-up defect the owner reported was never a routing defect:
the editor's Ask panel sent no `thread_id`, so every question was turn one and
the classifier had no antecedent to classify against (ticket 11, fixed in
17). `BaseRouter.PREAMBLE` already carries the locked follow-up instruction and
the runtime already supplies the conversation. A `follow_up` branch would need
a destination able to answer *any* prior intent — a node with no honest job.

## The mount is gone, and that is the ticket

Until ticket 10 this document had eight nodes and the `data_query` branch was
a `workflow.subgraph` onto a second package, `chinook-nl-to-sql`. Two
documents, one of them hidden, and the editor seeded the *hidden* one — which
is why the owner spent the whole map looking at a graph with no router in it.

Collapsing them buys three things beyond the obvious one:

- **The analyst stops re-classifying.** Its old prompt opened with a paragraph
  teaching it to notice that "hello" is not a database question — because it
  was reachable directly. Behind a router that already decided, that paragraph
  is dead weight, and it is gone.
- **The grader stops carrying a second copy of the same judgement.** Its old
  criteria began with the same is-this-even-a-database-question test, under
  `replace`, so it also discarded the built-in criteria. It now `extend`s them
  and says only what is true of *this* branch.
- **One package.** `tools/`, `data/`, `knowledge/`, `evals/` and `tests/` moved
  here from the deleted package. `pytest.ini`, the `Dockerfile`, `scripts/` and
  `docs/` all point at this directory now.

**The cost, recorded:** no *visible* example demonstrates a Team or Workflow
mount any more. The hidden `concierge` still does — it mounts this workflow
and `workflow-architect` as subgraphs — so `workflow.subgraph` is still
exercised by a shipped document and by `docs/patterns.md`, but a reader who
only ever opens the visible example will not meet composition. That was
accepted on the map before the work started.

## Why the analyst is an inline branch and not a Team

A Team is a supervisor plus workers, and a supervisor is a **planning model
call plus a fan-out and a join**. That buys something only when the run has to
name its own subtasks and several worker roles are waiting for them. This
branch has exactly one role and needs *retry until verified* — which is the
grader, not the supervisor.

No shipped example uses `team.workflow` as a result. That is the honest
outcome: the atom exists and is documented in `docs/patterns.md`, but this
example would have to pretend to need a planner to demonstrate it.

## Where each node's rules come from

Three layers, bottom to top — `default_rules` → the node's own field → a wired
skill (`docs/decisions/skill-layer.md`). What this document chose:

| Node | built-in | its own field | wired skill |
| --- | --- | --- | --- |
| `router1` | `BaseRouter.DEFAULT_RULES` — decide on need not phrasing, one branch, never answer | the five branch definitions | — |
| `agent-sql` | `AbstractAgentNode.DEFAULT_RULES` — use a tool rather than memory, never state a figure you did not obtain | **empty** | `sql-analyst.md` |
| `agent-chat` | same | its front-desk persona | — |
| `agent-web` | same | its search-then-fetch-then-cite order | — |
| `guard-web` | — | `check: web_answer_cites_its_source`, two attempts | — |
| `grader-sql` | `BaseGrader.DEFAULT_CRITERIA` | the Chinook-specific criteria, `rulesMode: extend` | — |

The bar this table is written against is the owner's: *"works out of the box
with minimum capability on any workflow."* Every node here still works with
its own field cleared and nothing wired, because the built-in layer is never
empty. `agent-sql` is the proof in the other direction — its field *is* empty,
and everything it knows about Chinook arrives through the `skill` port.

`skill-sql` is an `input.markdown` node. Its `instruction` carries the skill's
full text, frontmatter and all (`skills.py` strips the frontmatter before it
reaches the model, so `name:`/`description:` never leak into a prompt).
**Known gap, stated plainly:** the wire carries the *text*, not a path — there
is no node today that references a `.md` file on disk and re-reads it. "Write
the rules once and wire them into any workflow" is therefore achieved by
copying the node, not by pointing several documents at one file. The ambient
`workflows/<slug>/skills/*.md` directory is the other mechanism and rides as
context for *every* agent in a package, which is why the analyst's rules are
deliberately not in it: the Front Desk must not be taught SQL.

## What it costs

- **Greeting / off-topic / general knowledge** — two model calls: the router,
  then one agent. No tools, no grader.
- **Web lookup** — the router, then one agent loop with two tools, then a
  guard that costs nothing (a package function, no model) and one more agent
  lap if the answer states a figure without the URL it came from (two
  attempts max).
- **Data question** — the router, then one agent loop over three SQL tools,
  then a grader, and one more agent lap per rejection (three attempts max).
  The retry is the expensive part and it is on the only branch where a wrong
  answer looks exactly like a right one.

## The package

- `functions/cited_figures.py` — `web_answer_cites_its_source`, the check
  `guard-web` runs. The only package function here, and the only shipped
  demonstration of `guard.check` in this repository.
- `tools/` — the Chinook tool family (`tool.chinook-get-all-tables`,
  `tool.chinook-get-schema`, `tool.chinook-execute-sql`), read-only by
  construction.
- `data/Chinook_Sqlite.sqlite` — the repository's **single** sample database,
  the standard Chinook music store (Artist, Album, Track, Genre, MediaType,
  Customer, Invoice, InvoiceLine, Playlist, Employee).
- `knowledge/` — the second brain: eleven docs, one per table, so the agent
  knows what `InvoiceLine` means before it writes a join instead of inferring
  it from a schema dump. `openstategraph knowledge list .` prints the index.
- `evals/chinook.eval.json` — 36 graded cases, 31 answerable and 5 the
  database cannot answer. `openstategraph eval ./workflows/chinook-assistant`.
- `tests/` — the workflow's own pytest suite; `graph.py`/`agents.py` show
  the compiled output is plain Python that runs without the editor.

## Model

`settings.model` is `ollama:gpt-oss:120b-cloud` — Ollama **cloud**, never a
local model. A weak local model turns a wiring bug and a capability gap into
the same symptom; see CLAUDE.md.

## Tools

Five tool nodes, and the binding is per-agent, not per-workflow: the three
Chinook tools reach `agent-sql` only, the two web tools reach `agent-web`
only, and `agent-chat` holds none at all. That is what makes the Front Desk's
"never invent a figure" rule enforceable rather than hopeful — it has nothing
to invent one with.
