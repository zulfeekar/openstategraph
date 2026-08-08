# Wiki brief

Audience: coding agents (and the OpenStateGraph runtime's own read-only concierge
tools) plus OSS contributors. Document:

- The architecture: the compile seam (workflow.json → LangGraph StateGraph),
  the entity ladders (Interface → Abstract → Base → Concrete) on both sides,
  the middleware slot table, the registry/extension points.
- The workflow package contract (workflow.json, AGENTS.md, tools/, functions/,
  middlewares/, skills/) and how discovery binds each piece.
- Each shipped workflow: what it demonstrates and how to run it.
- The memory system (Store namespaces, checkpointers, skills as procedural).
- How to add: a node type, a tool, a middleware slot, a workflow, a Team.

Skip: generated artifacts, node_modules, .dev, dist, coverage, .scratch.
Prefer linking to real file paths over restating code.
