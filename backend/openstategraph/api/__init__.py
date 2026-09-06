"""**Not part of the public API. Stability is not guaranteed.**

Tier 3 (`docs/stability.md`): the editor's HTTP server, the workflow store,
capability discovery, model resolution and the registries. These are surfaces
the project *operates* — they exist to serve the canvas and the MCP layer — not
libraries for others to build on. Anything here may be renamed, split or
deleted in a patch release.

Two consequences worth stating plainly, because both are load-bearing:

- **The registries are deliberately not public.** `build_tool_registry`,
  `discover_tool_registry` and `discover_function_callables` are how the
  framework wires a package's own capabilities, and they must stay free to
  change shape. Extension is a *supported seam*, not a reachable object:
  subclass the ladders in `openstategraph.abc`, and — from ticket 05 —
  publish `[project.entry-points."openstategraph.tools"]` from your own
  distribution. If you find yourself importing a registry to extend the
  framework, that is a missing entry-point group, and it is a bug report we
  want.
- **`from openstategraph.api.main import app` is not a contract.** It is
  currently the only way to mount the server; that is a gap the console
  script closes, not permission.

The public surface is `openstategraph.__all__`, `openstategraph.abc` and
`openstategraph.errors`, plus the `workflow.json` schema.
"""
