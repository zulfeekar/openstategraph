---
title: Entity ladders and the middleware slot table
description: Interface → Abstract → Base → Concrete on both sides, and why middleware order is a slot table.
type: page
---

# Entity ladders and the middleware slot table

The house shape is **Interface → Abstract → Base → Concrete**
([`CLAUDE.md`](../../CLAUDE.md)): the interface is what consumers depend on,
the abstract holds shared capability, the base holds shared composition, and
concretes are leaves.

## Python ladders — [`backend/dyflow/abc/`](../../backend/dyflow/abc)

| File | Interface | Abstract / Base | Concrete |
| --- | --- | --- | --- |
| [`agent.py`](../../backend/dyflow/abc/agent.py) | `IAgent` | `AbstractAgentNode`, `BaseAgentNode` | `ReactAgentNode`, `DeepAgentNode`, `CustomGraphNode` |
| [`router.py`](../../backend/dyflow/abc/router.py) | `IRouter` | `BaseRouter` | `Router` |
| [`grader.py`](../../backend/dyflow/abc/grader.py) | `IGrader` | `BaseGrader` | `Grader` |
| [`orchestrator.py`](../../backend/dyflow/abc/orchestrator.py) | `IOrchestrator` | `BaseOrchestrator` | `Orchestrator` |
| [`tool.py`](../../backend/dyflow/abc/tool.py) | `ITool` | `BaseTool` | per-workflow tools |

Interfaces are `Protocol`s, so a plain callable or a third-party object can
satisfy them without inheriting.

Two rules the agent ladder enforces:

- **The base holds the minimum.** `AbstractAgentNode` owns `resolve_model` /
  `resolve_prompt` / `resolve_middleware` plus the template method that
  sequences them. A concrete supplies only its constructor and its slot preset.
- **`DeepAgentNode` is a sibling of `ReactAgentNode`, never a subclass.**
  `create_deep_agent` is `create_agent` plus a fixed slot assembly — the
  relationship is data, so it is a preset, not inheritance.

Retry/timeout/caching deliberately do **not** live on any of these bases; they
are [graph-assembly parameters](compile-seam.md).

### Tools wrap LangChain, never subclass it

`BaseTool` is ours; `as_langchain_tool()` adapts at the seam. Arguments are a
Pydantic model (`Args`) — the single source of truth — and errors are *data*
(`ToolResult.failure(...)`), so a model can read the error and retry instead of
the graph node dying.

### Locked prompt sections

`SystemPrompt` ([`prompt.py`](../../backend/dyflow/abc/prompt.py)) composes a
prompt from a locked machinery part and an editable rules part. The locked
`PREAMBLE`/`OUTPUT_CONTRACT` of each base is served read-only to the editor by
`GET /api/node-contracts`, rendered by
[`src/view/inspector/LockedPromptSections.tsx`](../../src/view/inspector/LockedPromptSections.tsx),
so nobody can duplicate or contradict it in an editable field.

## TypeScript ladder — [`src/nodes/`](../../src/nodes)

`INodeDefinition` (contract) → `AbstractNodeModel`
([`src/core/model/AbstractNodeModel.ts`](../../src/core/model/AbstractNodeModel.ts))
→ per-node model classes, declared with `defineNode()` from
[`ModelRegistry.ts`](../../src/core/model/ModelRegistry.ts). A tool node
subclasses [`AbstractToolNode.ts`](../../src/nodes/tools/AbstractToolNode.ts).
Each module exports both a definition and an `INodeExecutor` for the canvas
preview engine.

## The middleware slot table

[`backend/dyflow/abc/middleware.py`](../../backend/dyflow/abc/middleware.py).

LangChain middleware is a list whose order means **three things at once**:
`before_*` runs first-to-last, `after_*` runs last-to-first, `wrap_*` nests
with the first middleware outermost. So "append mine" or "priority 40"
expresses something that does not exist.

Therefore `MiddlewareSlotTable` is an ordered, **name-keyed** table:

- The base owns the canonical order —
  `AbstractAgentNode.SLOT_ORDER = ("skills", "filesystem", "subagents",
  "summarization", "limits", "patch-tool-calls")`.
- A contributor `set(name, middleware)`s a slot; replacement is by name.
- Unknown slot names flatten *after* the canonical ones, in first-set order.
- `flatten()` produces the list handed to `create_agent(middleware=[...])` at
  the last moment. Nothing wraps or patches a model object.

Merge order at runtime (`NodeRuntime`): tier preset → the workflow package's
`middlewares/` files → the node's own config. So a package file replaces a
preset slot, and a node setting still wins.
