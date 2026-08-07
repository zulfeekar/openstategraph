Type: grilling
Status: resolved v1 (2026-08-07) — 0274129
Blocked by: 33

## Question

`discover_functions` and `GET /api/workflows/{slug}/capabilities` list
functions, but `_builders` has exactly one function entry — the hardcoded
`function.format_report`. A discovered function can be seen and never run.
No workflow has a `functions/` directory.

Design executable function nodes:

- `BaseFunctionNode` (Python): a deterministic graph step, no model — the
  counterpart of a model-callable tool (the distinction `_format_report_function`'s
  docstring already draws).
- What is a function's signature contract? `(state) -> update` is maximal
  power and minimal safety; `(inputs: dict) -> str` is portable. Decide, and
  record how it serializes (expressions are a JSON AST — a function is
  *referenced by name*, never embedded).
- `function.*` node types register per-workflow, like discovered tools;
  `format_report` migrates from hardcoded to the first discovered example.
- Ports: how are a function's inputs/outputs declared? From its signature
  via inspection, or a manifest like tools?

## Resolution

`discover_function_callables` → `function.<name>` registry; contract fn(text)->str, no state access; raises become readable output; explicit builders can't be shadowed. Port declaration from signatures remains fog.
