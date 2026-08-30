# OpenStateGraph documentation

**OpenStateGraph is a framework built on top of LangGraph and LangChain**: a
document format (`workflow.json`), a compiler from it to a plain LangGraph
`StateGraph`, and the node semantics the compiler emits — organised by atomic
design, atoms through organisms. The canvas editor, the HTTP API and the MCP
layer are optional surfaces over those three.

Start with what you came here to do.

| I want to… | Read | Then |
| --- | --- | --- |
| **decide whether this is for me** | [What this is](what-is-this.md) — the framework sentence, the atomic-design tiers, how the shape compares to other Lang\*-layered frameworks, the measured dependency footprint, and when *not* to use it | [The stability contract](stability.md) |
| **understand what I am drawing** | [On the canvas](on-the-canvas.md) — the answers you need before the first drag: what a workflow is, the atom/molecule/organism tiers, how a revision loop is two edges, what a mount does (and why the Team card is gone), and why a template is a copy. Plus a glossary | [Patterns](patterns.md) |
| **try it in fifteen minutes** | [Getting started](getting-started.md) — `./start dev`, run the Chinook Assistant, ask it something in `/chat`. Or skip the clone: `openstategraph examples copy sql-qa` then `openstategraph run workflows/sql-qa "…"` — the gallery ships **inside the wheel**, and `workflows/` does not | [Patterns](patterns.md) |
| **use it in a project of my own** | [Using it in your project](adoption.md) — the three consumption modes (fork/checkout, artifact, MCP), the CLI, `load_workflow`, `RunResult`, `as_tool()`, and the draft → Publish → `/chat` lifecycle | [The stability contract](stability.md) |
| **wire it into an app I already own** | [Wiring a workflow into your app](wiring-it-in.md) — the two integration shapes and how to tell which you are in, a runnable `.astream_events()` → SSE loop for the embedded one, the four `configurable` identity keys in one table for both, and the consumer's half of the memory model | [The HTTP API](api.md) |
| **know what I can build, and how to arrange it** | [Patterns](patterns.md) — the seven arrangements mapped to our node vocabulary, with the criteria for choosing between them | [Ports and edges](ports-and-edges.md) |
| **measure whether my workflow is any good** | [Evaluation](evaluation.md) — `openstategraph eval`, execution accuracy (the metric Spider and BIRD report) and why it is not string comparison, how to add a case to a golden dataset, and how to read a regression | [Testing a second brain](second-brain.md) |
| **check that my workflow's knowledge is right** | [Testing a second brain](second-brain.md) — what a project-level second brain is, what to build and read, how to tell a *stale* doc from a *wrong* one, the ablation that says whether the store earns its place, and the three checks worth pinning in a test | [`decisions/knowledge-architecture.md`](decisions/knowledge-architecture.md) |
| **stop a right-looking number being wrong** | [Declaring a table](declaring-a-table.md) — the two fields a data source states about itself (`row_key`, `coverage`), why a `COUNT(*)` published under an entity noun is a claim, and why *"0 invoices"* over a table that stops in 2013 is not a measurement | [Ports and edges](ports-and-edges.md) |
| **stop my server's refusals going in circles** | [Declaring a next step](declaring-a-next-step.md) — the one field an MCP server puts on a refusal so a model has a destination and not just a prohibition, why *"change your approach"* alone leaves the same wrong moves available, and where to put it in an envelope that already forbids extra fields | [Declaring a table](declaring-a-table.md) |
| **add a capability that does not exist yet** | [Building an atom](building-an-atom.md) — a node definition, its Python half, the palette tiers, registration (including publishing your own distribution), and a worked example in ~60 lines | [Ports and edges](ports-and-edges.md) |
| **build my own UI on top of it** | [The HTTP API](api.md) — the committed OpenAPI document, the three SSE streams OpenAPI cannot express (with their event vocabulary and the terminal-frame guarantee), the calls a custom chat needs with real captured examples, a working client in one file, and the CORS rules | [`openapi.json`](openapi.json) |
| **have my own LLM compose the graph** | [The MCP layer](mcp.md) — client config, a worked transcript, the `compile_workflow` response shape, and the trust boundary | [`decisions/mcp-layer.md`](decisions/mcp-layer.md) |
| **know how far a workflow travels without us** | [Export and portability](export-and-portability.md) — whether a zero-dependency pure-LangGraph export exists, the MCP layer's tool list and open roadmap items, and why a Node/TypeScript export isn't planned | [Using it in your project](adoption.md) |
| **run it for other people** | [Deploying](deploying.md) — the threat model of an unauthenticated deployment, the committed Caddy and nginx configs (including what the SSE routes need), the optional shared token, and why a second worker is refused rather than discouraged | [`decisions/memory-architecture.md`](decisions/memory-architecture.md) |
| **know what can be taken away from me** | [The stability contract](stability.md) — the three tiers, the signature snapshot, the `workflow.json` version policy, the CLI's fixed exit codes, and the deprecation rules | [`../CHANGELOG.md`](../CHANGELOG.md) |
| **cut a release, or fix one that went wrong** | [Releasing](releasing.md) — the train from pull request to PyPI, the one human gate and what to check before clicking it, the branch protection and environment settings to configure by hand, and the rollback commands for a burned version number | [`decisions/sdk-practice.md`](decisions/sdk-practice.md) |
| **understand why it is shaped this way** | [`decisions/`](decisions/) — the arguments that were actually had | [`../CLAUDE.md`](../CLAUDE.md) |

Each page has exactly one job, and — with one deliberate exception — nothing
here restates another page. The exception is [On the canvas](on-the-canvas.md),
which is a **synthesis for a different reader**: someone drawing, who needs the
mount semantics, the loop rule and the class/instance model in one place before
they have any reason to open the pages those facts otherwise live in. It is
allowed to repeat; the pages below are not allowed to repeat each other:
[Ports and edges](ports-and-edges.md) is the only reference for the type
system; [adoption](adoption.md) is the only place the CLI's flags and exit
codes are enumerated for a consumer; [evaluation](evaluation.md) is the only
place the scoring metric is defined; [testing a second brain](second-brain.md)
is the only place the knowledge store's verification procedure is written down;
[stability](stability.md) is the only
place a promise is made about them; [the HTTP API](api.md) is the only place
the SSE event vocabulary is written down; [deploying](deploying.md) is the only
place authentication, the worker ceiling and the reverse proxy are explained;
[wiring it in](wiring-it-in.md) is the only place the identity keys are
collected for both integration shapes at once.

## The one idea underneath all of it

**Workflows have predetermined code paths; agents define their own process and
tool usage.** That single line orders everything on this canvas. It is a
spectrum, not a dichotomy, and every node type is a point on it:

```
predetermined ──────────────────────────────────────────────────► dynamic

route.classifier   function.format_report   orchestrate.supervisor   agent.llm
route.grader       workflow.subgraph        orchestrate.worker       (fat tool bus)
human.approval
```

On the left, *you* decide what happens next and the model only fills in the
blanks. On the right, the model decides — which tool to call, how many times,
when it is finished. Choosing where a step belongs on that line is the design
decision this documentation exists to help you make; everything else is
wiring.

The substrate for the whole line is the **augmented LLM**: a model with tool
calling, structured output and short-term memory. That is exactly one node —
`agent.llm`, with its `tools` bus, its `skill` input and its `prompt`. An
agent is a configured model; the patterns are how you arrange several of them.

## Where the rest lives

- [`../CLAUDE.md`](../CLAUDE.md) — the architecture contract. Non-negotiables,
  the layering rule, the LangGraph vocabulary, the portability guardrails.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — setup and the PR gate.
- [`../README.md`](../README.md) — running the app, extension points, providers.

LangGraph and LangChain facts in these pages come from the `docs-langchain`
MCP server, never from memory.
