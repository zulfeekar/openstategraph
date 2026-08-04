# Dyflow — AI Workflow Builder

A visual AI-agent workflow editor built on the **open-source** JointJS core
(`@joint/core`, MPL-2.0), reproducing the JointJS+ *AI Workflow Builder* demo
without any commercial packages.

Phase 1 (this repo) is the editor: canvas, design system, MVC engine, and a
pluggable provider layer that already runs workflows end to end. Phase 2 moves
execution behind a Python LangGraph/LangChain backend.

```bash
npm install
npm run dev        # http://localhost:5273
npm run build      # tsc -b && vite build
npm run typecheck
```

Opens on a seeded demo that **runs with no credentials** — the default model is
`Mock · Offline`, a deterministic simulator that exercises the real agent loop.

---

## What had to be rebuilt

`@joint/plus` ships the editor scaffolding; the open-source core ships only the
diagram primitives. Everything in the right column here is written from scratch
in this repo.

| JointJS+ feature | Open-source replacement |
| --- | --- |
| `ui.Stencil` | [`view/palette/Palette.tsx`](src/view/palette/Palette.tsx) — registry-driven, searchable, drag + click to add |
| `ui.PaperScroller` | [`canvas/Viewport.ts`](src/canvas/Viewport.ts) — transform-based infinite canvas, zoom about the pointer |
| `ui.Navigator` | [`view/minimap/Minimap.tsx`](src/view/minimap/Minimap.tsx) — draws model rects, not a second paper |
| `ui.Selection` | [`canvas/features/SelectionFeature.ts`](src/canvas/features/SelectionFeature.ts) — click, shift-click, rubber band |
| `ui.Snaplines` | [`canvas/features/SnaplinesFeature.ts`](src/canvas/features/SnaplinesFeature.ts) — 3×3 edge/centre alignment + snapping |
| `ui.Inspector` | [`view/inspector/Inspector.tsx`](src/view/inspector/Inspector.tsx) — rendered from field schemas |
| `ui.Toolbar` | [`view/topbar/TopBar.tsx`](src/view/topbar/TopBar.tsx) |
| `ui.Keyboard` | [`canvas/features/KeyboardFeature.ts`](src/canvas/features/KeyboardFeature.ts) — one binding table, shared with the help drawer |
| `dia.CommandManager` | [`core/commands/CommandStack.ts`](src/core/commands/CommandStack.ts) — undo/redo with coalescing + transactions |
| `format.*` (PNG/SVG/JSON) | [`view/export/exportWorkflow.ts`](src/view/export/exportWorkflow.ts) |
| `layout.DirectedGraph` | [`canvas/AutoLayout.ts`](src/canvas/AutoLayout.ts) — dagre via the MIT `@joint/layout-directed-graph` |
| HTML-in-shape | [`canvas/shapes/HtmlNode.ts`](src/canvas/shapes/HtmlNode.ts) — `foreignObject` + React portals |

---

## Architecture

Strict MVC with a framework-agnostic core. **`core/` imports neither React nor
JointJS** — it is plain TypeScript that could run in Node or a worker.

```
src/
├── design/        Design system — tokens, themes, primitives. No app logic.
├── core/          MODEL + engine. No React. No JointJS.
│   ├── kernel/        IDisposable, typed EventBus, generic Registry<T>, Result, geometry
│   ├── model/         contracts/ (interfaces) · AbstractNodeModel · WorkflowModel · ModelRegistry
│   ├── commands/      ICommand · CommandStack · node/edge commands
│   ├── validation/    ConnectionValidator (rule chain) · WorkflowValidator (diagnostics)
│   ├── serialization/ Versioned JSON + migration chain
│   ├── execution/     INodeExecutor · ExecutionEngine (topological scheduler)
│   └── providers/     ILLMProvider + Mock / Anthropic / OpenAI / Ollama adapters
├── controller/    WorkflowController façade · SelectionModel · ClipboardService
├── canvas/        VIEW (JointJS) — adapter, viewport, installable features
├── nodes/         Self-contained node modules (model + schema + ports + executor)
├── view/          VIEW (React) — shell, panels, node cards
└── app/           Composition root (Workbench) + React context + demo seed
```

### The one rule that makes it work

**The canvas is a projection of the model, never a peer.**

```
gesture → WorkflowController → ICommand → WorkflowModel → event → JointGraphAdapter → paper
```

`JointGraphAdapter` is strictly one-way (model → graph). No user gesture writes
to the graph and hopes the model catches up. Consequences:

- **Undo is generic.** It replays commands; no feature implements its own undo.
- **The graph is disposable.** Rebuilding it from the model is always correct —
  which is exactly what import does.
- **They cannot disagree.** There is no code path that mutates one without the
  other.

Drags are the interesting case: JointJS moves the element continuously while the
pointer is down (the graph leads), then `DragCommitFeature` rewinds the graph and
writes **one** `MoveNodesCommand` on release. Smooth drag, single undo entry.

### Extension points

Everything is a `Registry<T>`. Adding a capability is a registration, never an
edit to the engine.

| To add… | Register a… | Engine changes |
| --- | --- | --- |
| A node type | `INodeDefinition` + `INodeExecutor` | none |
| A tool the agent can call | `IToolExecutor` | none |
| An LLM vendor | `ILLMProvider` | none |
| A connection rule | `IConnectionRule` | none |
| A validation check | `IWorkflowRule` | none |
| A canvas behaviour | `IPaperFeature` | none |
| A bespoke card body | `NodeBody` | none |

A node module is one file: model class, field schema, ports, executor. See
[`nodes/tools/RedditSearchNode.ts`](src/nodes/tools/RedditSearchNode.ts) — a
complete tool in ~90 lines. `nodes/index.ts` is the only file that knows the
full catalogue.

### Content-driven cards

Node bodies are real HTML (React) inside a `foreignObject`, which is what makes
the typography, form controls and Markdown tables possible. Cards therefore
size *themselves*: after layout each card measures its height and the centre of
every port row and reports both to the adapter, which writes them onto the
JointJS cell so link endpoints land exactly on the dot the user sees.

That is a feedback loop, so it is made convergent deliberately — heights round to
whole model units and identical measurements are dropped before reaching the
model. See the comment block in
[`view/nodes/NodeCard.tsx`](src/view/nodes/NodeCard.tsx).

---

## Providers

| Provider | Credentials | Notes |
| --- | --- | --- |
| **Mock · Offline** | none | Default. Deterministic two-phase agent loop (requests a tool, then answers from its result) so the real execution path is exercised. |
| **Ollama** | none | Discovers locally pulled models from `/api/tags`. Start Ollama with `OLLAMA_ORIGINS="*"` so the browser can reach it. |
| **Anthropic** | API key | Official SDK, lazy-loaded. Adaptive thinking; drops to `thinking: disabled` below a 4096-token budget (`max_tokens` caps thinking *and* answer together) with the documented no-thinking guardrails applied. |
| **OpenAI** | API key | Official SDK, lazy-loaded. Model list refreshed from the account. |

Both vendor SDKs are dynamic imports, so they are separate chunks and cost
nothing for users who stay on Mock or Ollama.

> **Key storage:** keys are kept in this browser's `localStorage` and sent
> directly from the page to the provider. That is an acceptable trade for a
> local-first editor and it is stated plainly in the credentials dialog. Use a
> scoped, revocable key. Phase 2 removes browser-side keys entirely.

---

## Accessibility

The **Check accessibility** button runs a live DOM audit — accessible names on
every control, labelled node cards, keyboard reachability of canvas content,
reduced-motion support, and a measured WCAG contrast ratio for body text. It
inspects what is actually rendered, so it can genuinely fail.

Every canvas action has a keyboard equivalent; the bindings table drives both
the dispatcher and the shortcuts drawer, so the documentation cannot drift.

---

## Known limits

- **PNG export** rasterises the SVG through a canvas. Chromium does this with
  `foreignObject` content; WebKit historically refuses. The failure is reported
  with a message pointing at SVG export, which always works.
- **SVG export** inlines the app's stylesheets and resolved theme variables but
  drops `@font-face` rules, so an external viewer falls back to a system font.
- **Reddit tool** tries the live endpoint first and falls back to labelled
  sample data — Reddit rejects browser-origin requests. The fallback is marked
  in both the payload and the run log rather than passed off as live.
- **Containers do not auto-fit** their children, by design: an auto-growing
  frame changes geometry behind the user's back, and geometry belongs to the
  model. Frames are resized by hand via the corner grip.
- **Execution is sequential**, so a run is legible on the canvas. Parallelising
  independent branches is a change to `ExecutionEngine.run` alone.

---

## Phase 2 — LangGraph backend

The seam is already in place: `ILLMProvider` and `INodeExecutor`. A
`LangGraphProvider` (or a `HttpWorkflowExecutor` that posts the serialized
workflow to a Python service) registers alongside the existing adapters and
nothing else changes — the canvas, palette, inspector and command stack are
already vendor-agnostic.

The serialized document ([`core/serialization`](src/core/serialization/WorkflowSerializer.ts))
is versioned with a migration chain and is the natural wire format for
compiling a graph into a LangGraph `StateGraph`.

**MCP note:** `docs-langchain` (https://docs.langchain.com/mcp) is connected in
this workspace. `reference-langchain` (https://reference.langchain.com/mcp) is
**not** yet — add it before phase 2 so API signatures come from the reference
rather than from memory.
