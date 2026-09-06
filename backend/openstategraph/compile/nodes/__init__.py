"""One module per node family: what each kind of node *does* once it is built.

`docs-and-gaps/03`, and the argument for it is `CLAUDE.md`'s **O**:

> extend by **registering**, never by editing the engine. Every extension
> point is a `Registry<T>`.

`NodeRuntime._register_node_types` was already that registry and `builder_for`
already that dispatch — with every one of twenty implementations inlined
behind them. Twenty families in one file is the registry pattern with the
bodies left in the engine, and `rules-that-can-fail/04` records the
consequence exactly: the class passed the public-surface census at nine
members every single time somebody added a twenty-first reason for it to
change, because the clause that would have caught it — *one reason to change*
— had no instrument.

## How a family is bound, and why the first parameter is still called `self`

Each module here declares plain functions whose first parameter is the
runtime, and `NodeRuntime`'s class body binds them as its own attributes:

    class NodeRuntime:
        _router = router._router
        _grader = grader._grader

A function assigned in a class body **is** a method. So
`runtime._router(node_id, node, plan)` calls it exactly as before, and
`inspect.getsource(NodeRuntime._router)` returns the source over here.

Naming the parameter `self` is not a stylistic tic and not a disguise. These
*are* methods; they are simply written outside the class body, which Python
has always allowed. Spelling it `runtime` instead was tried first and rejected
on evidence, because it would have meant rewriting every `self.` in roughly a
thousand lines — turning a pure move into a diff nobody can review — and
because two censuses read a builder's body looking for exact call shapes.
`test_data_key_contract.py` went red on `runtime._resolve_model(data, node_id)`
with the message *"teach this extractor the new form — silently skipping it
would leave the contract passing while guarding nothing"*, which is the
warning taken. Keeping `self` keeps every body **byte-identical**: the diff of
this split is a move and can be read as one.

## What that buys, checked rather than assumed

- **No signature moved.** Eleven test sites call `runtime._agent(...)`
  directly, and more call `_subgraph`, `_router`, `_worker`, `_grader`,
  `_output`, `_input` and `_passthrough`. A façade would have broken all of
  them for nothing.
- **Five source censuses keep working, unedited.**
  `test_model_field_contract.py`, `test_skill_layer_contract.py` and
  `test_reasoning_effort.py` walk `runtime._builders` and call
  `inspect.getsource` on each value; `test_branch_context.py` does it to
  `NodeRuntime._agent` by name; `test_data_key_contract.py` parses each
  builder's AST. Registering a `functools.partial` or a delegating one-liner
  would have left every one of them **green and blind** — which is the exact
  defect this split is filed under. Binding the function itself is what makes
  the census follow the code.
- **`test_node_type_registry.py` checks each registered builder's
  `__name__`**, which is why the functions keep their original names rather
  than becoming a uniform `build`.

An import-time `@register("agent.llm")` decorator was the obvious alternative
and is deliberately not used. `_register_node_types` states the house answer
in its own docstring — *"adding a built-in node type is still a line in this
method, and that is the honest reading of CLAUDE.md's O rather than a hole in
it: a built-in is the engine"* — and it is right. A registry whose contents
depend on which modules happened to be imported cannot be read off the page,
and none of this repository's other registries works that way. Extending the
engine **from outside** still needs no edit there and never did: that is
`openstategraph.node_families`, the entry-point group, untouched.

## What a family may see, and the honest cost

A family module reaches the runtime's own attributes — `self._types`,
`self._bind_tools(...)`, `self.services`. That is a **file** boundary, not an
encapsulation boundary, and pretending otherwise would be the split in name
only that the ticket warns about.

It is the right boundary anyway, for the reason `CLAUDE.md` records about
`WorkflowModel`: `AdjacencyIndex` and `GraphQueries` hold the real
implementations and are independently tested, while the class that owns them
stays the thing consumers name. A built-in family **is** the engine, and the
engine is entitled to itself.

The genuinely narrowed seam already exists and is not this one. It is
`NodeBuildContext` in `openstategraph/abc/node_family.py`, which names three
capabilities and whose docstring says the presumption is against a fourth.
That is the published contract for a *plugin*; nothing here widens it, and
these functions must never become the reason it grows.

What the boundary does buy is what the ticket asked for: one reason to change
per module, and a family's dependency on the runtime made greppable in a file
with its own import list, instead of invisible among a thousand other `self.`
references.
"""
