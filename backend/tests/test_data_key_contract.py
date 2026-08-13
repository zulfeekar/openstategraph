"""Every `data` key a node factory reads is a key some node type declares.

**The general form of a defect that has now shipped three times.** A factory
reads `data["x"]`; no node type declares a field keyed `x`; nothing raises,
because a missing key is simply `""` forever. The three instances:

1. the model picker — declared on `agent.llm` while `_resolve_model` read
   `data["model"]` for six node types, so five nodes ran whichever model the
   request resolved and no card could say otherwise;
2. the Worker's rules mode — `_worker` composed a wired skill as `wired or
   default`, i.e. `replace` hardcoded, so its `rulesMode` select reached
   nothing;
3. the supervisor's rules — `_orchestrator` passed `rules=_text(data,
   "instruction")`, and `instruction` is that node's input *port* id, not a
   data key. Every supervisor ever built dispatched with empty rules.

The first two were caught by `test_model_field_contract.py` and
`test_skill_layer_contract.py`, each of which pins exactly one shared field.
This is the same guard generalised over *every* key, so instance four fails
here instead of shipping: the editor emits each node type's `field_keys` into
`port_specs.json`, and the reads are extracted from the compiler's own source.

**What it deliberately does not assert: the other direction.** A declared field
the factory never reads is not a defect — `maxRetries` and `timeoutSeconds` are
graph-assembly parameters the compiler reads, a worker's `role` is read by the
*supervisor's* factory rather than its own, and a tool node's fields are read by
the tool implementation. Only "read but undeclared" is unambiguous, so only that
is a test.

**The extractor is deliberately strict rather than clever.** It follows literal
keys through direct reads, through `_text(data, "key")`, and into any helper
called with the data dict (`self._resolve_model(data)`, `_replaces_rules(data)`)
— and it *fails* on a read it cannot resolve to a literal. Keeping data keys
literal at the point of use is a cheap convention; the alternative is a guard
that quietly stops guarding the moment someone introduces an indirection.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import pytest

from openstategraph.compile import node_runtime
from openstategraph.compile.node_catalogue import load_catalogue
from openstategraph.compile.node_runtime import NodeRuntime

#: The factory parameter holding the whole node record. `node.get("data")` on
#: *this* name is this node's own data; the same call on any other name is
#: another node's (`worker_node.get("data")` in `_orchestrator`), which a node
#: type cannot be held responsible for declaring.
NODE_PARAM = "node"


class _Reads(ast.NodeVisitor):
    """Literal `data` keys read in one function body."""

    def __init__(self, runtime: NodeRuntime, names: set[str], seen: set[Any]) -> None:
        self.runtime = runtime
        self.names = set(names)
        self.seen = seen
        self.keys: set[str] = set()
        #: Reads that resolve to no literal — reported as failures, not ignored.
        self.opaque: set[str] = set()

    def _is_data(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.names
        # `node.get("data") or {}` — the idiom every factory opens with.
        if isinstance(node, ast.BoolOp):
            return any(self._is_data(value) for value in node.values)
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == NODE_PARAM
            and bool(node.args)
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "data"
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_data(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.names.add(target.id)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_data(node.value):
            key = _literal_key(node.slice)
            if key is not None:
                self.keys.add(key)
            else:
                self.opaque.add(ast.unparse(node))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and self._is_data(func.value):
            key = _literal_key(node.args[0]) if node.args else None
            if key is not None:
                self.keys.add(key)
            else:
                self.opaque.add(ast.unparse(node))
        elif node.args and self._is_data(node.args[0]):
            self._visit_delegate(node, func)
        self.generic_visit(node)

    def _visit_delegate(self, node: ast.Call, func: ast.expr) -> None:
        """A call handed the data dict: `_text(data, "k")`, or a helper."""
        second = node.args[1] if len(node.args) > 1 else None
        key = _literal_key(second)
        if key is not None:
            self.keys.add(key)
            return
        target = _resolve(func, self.runtime)
        if target is None:
            self.opaque.add(ast.unparse(node))
            return
        params = _params(target)
        keys, opaque = _reads(target, self.runtime, self.seen, params[0] if params else None)
        self.keys |= keys
        self.opaque |= opaque


def _literal_key(node: ast.expr | None) -> str | None:
    """The string a key expression names — literal, or a module constant.

    A shared key spelled once as a constant (`REASONING_EFFORT_KEY`, imported
    into `node_runtime`) is *more* disciplined than a repeated literal, not
    less, so resolving it is not a loosening: the value is still fixed at
    import and still checkable. What stays unresolvable, and therefore a
    failure, is a key computed at run time.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        value = getattr(node_runtime, node.id, None)
        if isinstance(value, str):
            return value
    return None


def _resolve(func: ast.expr, runtime: NodeRuntime) -> Callable[..., Any] | None:
    """The Python object a called name refers to, module-level or on the runtime."""
    if isinstance(func, ast.Name):
        return getattr(node_runtime, func.id, None)
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
    ):
        return getattr(runtime, func.attr, None)
    return None


def _params(fn: Callable[..., Any]) -> list[str]:
    try:
        return list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):  # pragma: no cover - builtins only
        return []


def _reads(
    fn: Callable[..., Any],
    runtime: NodeRuntime,
    seen: set[Any],
    data_param: str | None,
) -> tuple[set[str], set[str]]:
    """Keys read by `fn`, following helpers it hands the data dict to.

    `data_param` names the parameter that *is* the data dict — set for a helper
    like `_text(data, key)`, `None` for a factory, whose data arrives as
    `node.get("data")` and is picked up from the assignment instead.
    """
    if fn in seen:
        return set(), set()
    seen.add(fn)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):  # pragma: no cover - source is present here
        return set(), set()
    visitor = _Reads(runtime, {data_param} if data_param else set(), seen)
    visitor.visit(tree)
    return visitor.keys, visitor.opaque


@pytest.fixture(scope="module")
def factories() -> dict[Any, set[str]]:
    """Factory -> the node types it builds, for every type in the catalogue.

    Inverted from `NodeRuntime.builder_for`, which is the compiler's own
    dispatch — not a list kept in step by hand, which is the class of bug these
    contracts exist to catch. Grouping by factory matters because one factory
    can serve several types: `_input` builds both `input.text` and
    `input.markdown` and reads `prompt` on one and `instruction` on the other.
    """
    runtime = NodeRuntime(model=None)
    served: dict[Any, set[str]] = defaultdict(set)
    for node_type in sorted(load_catalogue().node_types):
        served[runtime.builder_for(node_type)].add(node_type)
    return dict(served)


class TestEveryKeyAFactoryReadsIsDeclared:
    def test_no_factory_reads_a_key_no_node_type_can_write(
        self, factories: dict[Any, set[str]]
    ) -> None:
        runtime = NodeRuntime(model=None)
        catalogue = load_catalogue()
        declared_by = catalogue.field_keys
        failures: list[str] = []
        for factory, node_types in factories.items():
            keys, _ = _reads(factory, runtime, set(), None)
            # The union over the types this one factory serves: a shared
            # factory legitimately reads a key only one of its types declares.
            declared = set(catalogue.legacy_data_keys)
            for node_type in node_types:
                declared |= declared_by.get(node_type, frozenset())
            missing = keys - declared
            if missing:
                failures.append(
                    f"{factory.__name__} (builds {sorted(node_types)}) reads {sorted(missing)}"
                )
        assert not failures, (
            "These factories read `data` keys the editor declares no field for, so "
            "nothing on a card, in the inspector or in a document can ever write "
            'them — the read silently yields "" forever:\n  '
            + "\n  ".join(failures)
            + "\nDeclare the field in `src/nodes/**` and run `npm run generate:ports`, "
            "or stop reading the key."
        )

    def test_every_data_read_resolves_to_a_literal_key(
        self, factories: dict[Any, set[str]]
    ) -> None:
        """The guard's own honesty check.

        An extractor that shrugs at what it cannot parse degrades to passing
        while covering nothing, which is how the three shipped defects felt from
        the inside. So a read this cannot resolve to a literal is a failure, and
        the fix is to keep the key literal at the point of use.
        """
        runtime = NodeRuntime(model=None)
        opaque: dict[str, set[str]] = {}
        for factory in factories:
            _, unresolved = _reads(factory, runtime, set(), None)
            if unresolved:
                opaque[factory.__name__] = unresolved
        assert not opaque, (
            "These reads of a node's `data` do not resolve to a literal key, so the "
            f"data-key contract cannot check them: {opaque}. Keep the key a string "
            "literal at the point of use, or teach this extractor the new form — "
            "silently skipping it would leave the contract passing while guarding "
            "nothing."
        )

    def test_the_extractor_is_not_vacuously_empty(self, factories: dict[Any, set[str]]) -> None:
        """A contract that passes because it found nothing is no contract."""
        runtime = NodeRuntime(model=None)
        found: set[str] = set()
        for factory in factories:
            keys, _ = _reads(factory, runtime, set(), None)
            found |= keys
        # Spot-checks across three families and both read idioms: `_text(data,
        # ...)`, `data.get(...)`, and a key reached only through a helper.
        assert {"model", "rulesMode", "rubric", "branches", "maxSubtasks"} <= found
        assert len(found) >= 15


class TestTheSupervisorsRulesAreWritable:
    """The third instance, pinned specifically.

    `_orchestrator` read `instruction` — the node's input *port* id — so its
    `rules=` argument was empty for every supervisor ever built. A general
    contract would have caught it; it is pinned by name as well because the
    port and the field sit one line apart and the next edit here is the one
    most likely to reintroduce it.
    """

    def test_the_supervisor_declares_the_rules_field_its_factory_reads(self) -> None:
        runtime = NodeRuntime(model=None)
        keys, _ = _reads(runtime.builder_for("orchestrate.supervisor"), runtime, set(), None)
        assert "rules" in keys
        assert "rules" in load_catalogue().field_keys["orchestrate.supervisor"]

    def test_the_instruction_port_is_not_read_as_a_data_key(self) -> None:
        runtime = NodeRuntime(model=None)
        keys, _ = _reads(runtime.builder_for("orchestrate.supervisor"), runtime, set(), None)
        ports = load_catalogue().port_specs["orchestrate.supervisor"]
        assert "instruction" in ports, "the port this defect was named after still exists"
        assert "instruction" not in keys

    def test_inline_rules_reach_the_supervisors_prompt(self) -> None:
        """End to end, through the factory rather than through `Orchestrator`.

        `test_orchestrator.py` already proves `Orchestrator(rules=...)` renders
        its rules; what shipped broken was the wiring between the document and
        that argument, so the assertion has to start at a document.
        """
        from openstategraph.compile.workflow_compiler import CompiledPlan

        runtime = NodeRuntime(model=None)
        node = {
            "id": "sup",
            "type": "orchestrate.supervisor",
            "data": {"rules": "Send anything numeric to the analyst."},
        }
        runtime.factory({"nodes": [node]})
        captured: list[str] = []

        class _Spy:
            def __init__(self, **kwargs: Any) -> None:
                captured.append(kwargs["rules"])

            def plan(self, *_args: Any, **_kwargs: Any) -> list[Any]:
                return []

        monkey = node_runtime.Orchestrator
        node_runtime.Orchestrator = _Spy  # type: ignore[misc]
        try:
            runtime.builder_for("orchestrate.supervisor")("sup", node, CompiledPlan())
        finally:
            node_runtime.Orchestrator = monkey  # type: ignore[misc]

        assert captured and captured[0] == "Send anything numeric to the analyst."


class TestEveryKeyWeShipIsAKeySomethingReads:
    """The third direction — and the one instance four actually shipped through.

    The class above asserts *read but undeclared*. Its docstring explains why
    the reverse (*declared but unread*) is deliberately not asserted: a
    declared field the factory never reads is legitimate.

    There is a third direction, and it is unambiguous: **a `data` key written
    into a document we ship, which no node type declares.** Nothing can read
    it, no card or inspector can show it, and it is silently discarded at
    compile time — so a developer edits it and nothing happens.

    Instance four, found 2026-08-13 and fixed by this test: the `team`
    scaffold shipped `"instruction": "Split the task into the smallest set of
    independent subtasks."` on its supervisor. `instruction` is that node's
    input *port* id — which is instance **three** in this file's own docstring.
    The compiler was corrected to read `rules`; the template that writes it
    never was. So the guard written because of instance three could not see
    instance four, because it was pointed the other way.

    Every package scaffolded from `team` carried a dispatch instruction that
    did nothing.
    """

    @staticmethod
    def _declared() -> dict[str, set[str]]:
        specs = json.loads(
            (Path(__file__).resolve().parents[1]
             / "openstategraph/compile/port_specs.json").read_text()
        )
        return {
            entry["type"]: set(entry["field_keys"]) | set(entry.get("legacy_data_keys") or [])
            for entry in specs["node_types"]
        }

    @staticmethod
    def _shipped() -> list[Path]:
        root = Path(__file__).resolve().parents[2]
        return sorted(
            list((root / "backend/openstategraph/templates").glob("*/workflow.json"))
            + list((root / "workflows").glob("*/workflow.json"))
        )

    def test_no_shipped_document_writes_a_key_no_node_type_declares(self) -> None:
        declared = self._declared()
        offences: list[str] = []
        for path in self._shipped():
            document = json.loads(path.read_text())
            document = document.get("document", document)
            for node in document.get("nodes") or []:
                known = declared.get(node["type"])
                if known is None:
                    continue  # a workflow-scoped type that does not ship in the catalogue
                for key in (node.get("data") or {}):
                    if key not in known:
                        offences.append(
                            f"{path.parent.name}/{node['id']} ({node['type']}) "
                            f"writes '{key}', which no node type declares"
                        )
        assert offences == [], "\n".join(offences)

    def test_the_sweep_actually_looked_at_something(self) -> None:
        # A glob that silently matched nothing would make the test above pass
        # forever — the same vacuity guard the class above keeps.
        shipped = self._shipped()
        assert len(shipped) >= 5
        assert any("templates" in str(p) for p in shipped)
