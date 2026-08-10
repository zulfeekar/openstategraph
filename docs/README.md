# OpenStateGraph documentation

**OpenStateGraph is a framework built on top of LangGraph and LangChain**: a
document format (`workflow.json`), a compiler from it to a plain LangGraph
`StateGraph`, and the node semantics the compiler emits — organised by atomic
design, atoms through organisms. The canvas editor, the HTTP API and the MCP
layer are optional surfaces over those three.

Start with what you came here to do.

| I want to… | Read | Then |
| --- | --- | --- |
| **decide whether this is for me** | [What this is](what-is-this.md) — the framework sentence, the atomic-design tiers, how the shape compares to other Lang\*-layered frameworks, the measured 36-distribution footprint, and when *not* to use it | [The stability contract](stability.md) |
| **try it in fifteen minutes** | [Getting started](getting-started.md) — `./start dev`, run Store Analytics, ask it something in `/chat`. Or skip the clone: `openstategraph run ./workflows/chinook-nl-to-sql "…"` | [Patterns](patterns.md) |
| **use it in a project of my own** | [Using it in your project](adoption.md) — the three consumption modes (fork/checkout, artifact, MCP), the CLI, `load_workflow`, `RunResult`, `as_tool()`, and the draft → Publish → `/chat` lifecycle | [The stability contract](stability.md) |
| **know what I can build, and how to arrange it** | [Patterns](patterns.md) — the seven arrangements mapped to our node vocabulary, with the criteria for choosing between them | [Ports and edges](ports-and-edges.md) |
| **add a capability that does not exist yet** | [Building an atom](building-an-atom.md) — a node definition, its Python half, the palette tiers, registration (including publishing your own distribution), and a worked example in ~60 lines | [Ports and edges](ports-and-edges.md) |
| **build my own UI on top of it** | [The HTTP API](api.md) — the committed OpenAPI document, the three SSE streams OpenAPI cannot express (with their event vocabulary and the terminal-frame guarantee), the five calls a custom chat needs with real captured examples, a forty-line working client, and the CORS rules | [`openapi.json`](openapi.json) |
| **have my own LLM compose the graph** | [The MCP layer](mcp.md) — client config, a worked transcript, the `compile_workflow` response shape, and the trust boundary | [`decisions/mcp-layer.md`](decisions/mcp-layer.md) |
| **run it for other people** | [Deploying](deploying.md) — the threat model of an unauthenticated deployment, the committed Caddy and nginx configs (including what the SSE routes need), the optional shared token, and why a second worker is refused rather than discouraged | [`decisions/memory-architecture.md`](decisions/memory-architecture.md) |
| **know what can be taken away from me** | [The stability contract](stability.md) — the three tiers, the signature snapshot, the `workflow.json` version policy, the CLI's fixed exit codes, and the deprecation rules | [`../CHANGELOG.md`](../CHANGELOG.md) |
| **cut a release, or fix one that went wrong** | [Releasing](releasing.md) — the train from pull request to PyPI, the one human gate and what to check before clicking it, the branch protection and environment settings to configure by hand, and the rollback commands for a burned version number | [`decisions/sdk-practice.md`](decisions/sdk-practice.md) |
| **understand why it is shaped this way** | [`decisions/`](decisions/) — the arguments that were actually had | [`../CLAUDE.md`](../CLAUDE.md) |

Each page has exactly one job, and nothing here restates another page:
[Ports and edges](ports-and-edges.md) is the only reference for the type
system; [adoption](adoption.md) is the only place the CLI's flags and exit
codes are enumerated for a consumer; [stability](stability.md) is the only
place a promise is made about them; [the HTTP API](api.md) is the only place
the SSE event vocabulary is written down; [deploying](deploying.md) is the only
place authentication, the worker ceiling and the reverse proxy are explained.

## The one idea underneath all of it

**Workflows have predetermined code paths; agents define their own process and
tool usage.** That single line orders everything on this canvas. It is a
spectrum, not a dichotomy, and every node type is a point on it:

```
predetermined ──────────────────────────────────────────────────► dynamic

route.classifier   function.format_report   orchestrate.supervisor   agent.llm
route.grader       workflow.subgraph        orchestrate.worker       (fat tool bus)
human.approval     team.workflow
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
