# OpenStateGraph documentation

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

## The pages

| Page | What it answers |
| --- | --- |
| [**Getting started**](getting-started.md) | You cloned it — now what? Checkout → `./start dev` → run Store Analytics → ask it something in `/chat`. Prerequisites, model credentials, and the two value journeys (developer, end user). |
| [**Using it in your project**](adoption.md) | The fine-day question. The three consumption modes — fork/checkout, artifact, MCP — with exact commands, the upgrade friction stated honestly, what artifacts you own, and the draft → Publish → `/chat` story. |
| [**The MCP layer**](mcp.md) | Point your own LLM client at it and have *it* compose the graph. Client config, a worked transcript with a document that genuinely validates, the `compile_workflow` response shape, and why the client renders the compiled Mermaid as a diagram locally. |
| [**Patterns**](patterns.md) | The seven arrangements — augmented LLM, prompt chaining, routing, parallelization, orchestrator-worker, evaluator-optimizer, agent — each mapped to our node vocabulary, with selection criteria and a diagram. |
| [**Building an atom**](building-an-atom.md) | The walkthrough. Anatomy of a node definition, the Python half, registration, the TDD loop and the five gates, and a complete worked example in ~60 lines. |
| [**Ports and edges**](ports-and-edges.md) | Reference. Port types, cardinality, edge categories, why `feedback` is the only cycle-closer, and the colour/dash legend that matches the canvas. |

## Where the rest lives

- [`../CLAUDE.md`](../CLAUDE.md) — the architecture contract. Non-negotiables,
  the layering rule, the LangGraph vocabulary, the portability guardrails.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — setup and the PR gate.
- [`../README.md`](../README.md) — running the app, extension points, providers.
- [`decisions/`](decisions/) — decision records for the choices that were
  argued out.

LangGraph and LangChain facts in these pages come from the `docs-langchain`
MCP server, never from memory.
