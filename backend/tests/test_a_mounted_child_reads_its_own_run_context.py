"""A mounted child reads its own run context — `organisms-first-class/76`.

The composition half of the channel `docs/decisions/runtime-context.md` builds.
`71` made a node read a value; the first thing that read one at a mount
boundary found this, and it was measured before it was fixed. A mount is a
closure over the child's `invoke()` (`compile/composition.py`), so LangGraph
carried the **parent's** runtime down it, and against langgraph 1.2.10 the
child's own document decided nothing at all:

| parent declares | child declares | what the child's node saw |
| --- | --- | --- |
| `tenant`, `locale=fr-FR` | `locale` default `en-GB` | `{tenant, locale: fr-FR}` |
| `tenant`, `locale=fr-FR` | *(nothing)* | `{tenant, locale: fr-FR}` |
| *(nothing)* | `locale` default `en-GB` | `{}` |
| `tenant`, `locale=fr-FR` | *(nothing)*, mounting a grandchild declaring `locale` | `{tenant, locale: fr-FR}`, two levels down |

Both failure modes the chain exists to remove, in one seam: a child read a
field it never declared, and a field it *did* declare was silently absent.

**The shape chosen is inherit-then-narrow**, and it mirrors `582e098`'s rule
for the step budget exactly — the caller's run is the ceiling, the child's own
document is the aperture. A key crosses a mount only when **both** documents
declare it; the child's own defaults fill everything else; a key the child
never declared is not visible to it at any depth.

**What would still be green if the wrong thing were built?** A unit test of the
narrowing function alone, against a mount that never calls it. So every case
below compiles a real parent and a real child with the real `WorkflowCompiler`
and the real `NodeRuntime`, really runs the composition, and asserts either on
the answer text a child's node rendered or on what a node inside the child
actually read through the same `run_context()` accessor the text families use.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.run_context import run_context, validate_run_context
from openstategraph.compile.workflow_compiler import WorkflowCompiler, parse_failure_marker

#: Obvious placeholders: a feature about tenants is exactly where a real
#: looking identity slips into a repository.
TENANT = "tenant-placeholder"

PARENT_DECLARATION = [
    {"key": "tenant", "type": "string", "label": "Tenant", "required": True},
    {"key": "locale", "type": "string", "label": "Locale", "default": "fr-FR"},
]
CHILD_DECLARATION = [{"key": "locale", "type": "string", "label": "Locale", "default": "en-GB"}]


def _document(
    name: str,
    *,
    context: Any = None,
    mounts: str | None = None,
    prompt: str = "",
    probe: bool = False,
) -> dict[str, Any]:
    """`input -> (mount | probe | nothing) -> output`, with no model in it."""
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": prompt}}
    ]
    edges: list[dict[str, Any]] = []
    if mounts is not None:
        nodes.append(
            {
                "id": "m1",
                "type": "workflow.subgraph",
                "position": {"x": 100, "y": 0},
                "data": {"workflow": mounts},
            }
        )
        edges.append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "m1", "portId": "input"},
            }
        )
        tail, tail_port = "m1", "result"
    elif probe:
        nodes.append(
            {"id": "m1", "type": "function.probe", "position": {"x": 100, "y": 0}, "data": {}}
        )
        edges.append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "m1", "portId": "candidate"},
            }
        )
        tail, tail_port = "m1", "report"
    else:
        tail, tail_port = "in1", "text"
    nodes.append({"id": "out1", "type": "output.formatted", "position": {"x": 300, "y": 0}, "data": {}})
    edges.append(
        {
            "source": {"nodeId": tail, "portId": tail_port},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    )
    document: dict[str, Any] = {"version": 1, "name": name, "nodes": nodes, "edges": edges}
    if context is not None:
        document["settings"] = {"context": context}
    return document


class Probe:
    """What a node *inside* a mounted document actually read.

    The same `run_context()` accessor `_input` and `_static_text` call, so this
    is not a second reading of the channel — it is the one reading, observed
    from a node the test can put anywhere in a composition.
    """

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def __call__(self, text: str) -> str:
        self.seen.append(dict(run_context()))
        return text


def _run(
    parent: dict[str, Any],
    children: dict[str, dict[str, Any]],
    supplied: Any = None,
    *,
    probe: Probe | None = None,
    question: str = "",
) -> dict[str, Any]:
    runtime = NodeRuntime(
        document_loader=children.__getitem__,
        functions={"function.probe": probe or Probe()},
    )
    graph = WorkflowCompiler().build(parent, RunState, runtime.factory(parent))
    checked = validate_run_context(parent, supplied)
    extra = {} if checked is None else {"context": checked}
    return graph.invoke(
        {"question": question, "messages": [], "attempts": 0, "decisions": {}, "outputs": {}},
        **extra,
    )


def _answer(result: dict[str, Any]) -> str:
    return str(result.get("answer") or result.get("outputs", {}).get("out1") or "")


# --------------------------------------------------------------------------- #
# The demonstration: a mounted child's own text, rendered from its own
# declaration, through a real composition.
# --------------------------------------------------------------------------- #


class TestWhatAMountedChildRenders:
    def test_a_childs_own_default_materialises_when_the_parent_declares_nothing(self) -> None:
        child = _document("child", context=CHILD_DECLARATION, prompt="locale is {{locale}}")
        result = _run(_document("parent", mounts="child"), {"child": child})
        assert _answer(result) == "locale is en-GB"

    def test_a_key_both_documents_declare_carries_the_runs_value(self) -> None:
        child = _document("child", context=CHILD_DECLARATION, prompt="locale is {{locale}}")
        parent = _document("parent", context=PARENT_DECLARATION, mounts="child")
        result = _run(parent, {"child": child}, {"tenant": TENANT})
        assert _answer(result) == "locale is fr-FR"

    def test_a_key_the_child_never_declared_is_not_rendered_for_it(self) -> None:
        """The leak, stated as an author would meet it.

        `tenant` is a live, supplied value of this run. The child never asked
        its caller for it, so its `{{tenant}}` stays byte-identical — the same
        answer an unresolved placeholder gets everywhere else (71).
        """
        child = _document("child", context=CHILD_DECLARATION, prompt="tenant is {{tenant}}")
        parent = _document("parent", context=PARENT_DECLARATION, mounts="child")
        result = _run(parent, {"child": child}, {"tenant": TENANT})
        assert _answer(result) == "tenant is {{tenant}}"
        assert TENANT not in _answer(result)


# --------------------------------------------------------------------------- #
# What a node inside the child actually read — the whole mapping, at depth.
# --------------------------------------------------------------------------- #


class TestWhatAMountedChildReads:
    def test_the_child_sees_its_declared_keys_and_nothing_else(self) -> None:
        probe = Probe()
        child = _document("child", context=CHILD_DECLARATION, probe=True)
        parent = _document("parent", context=PARENT_DECLARATION, mounts="child")
        _run(parent, {"child": child}, {"tenant": TENANT}, probe=probe)
        assert probe.seen == [{"locale": "fr-FR"}]

    def test_a_child_declaring_nothing_reads_nothing(self) -> None:
        probe = Probe()
        child = _document("child", probe=True)
        parent = _document("parent", context=PARENT_DECLARATION, mounts="child")
        _run(parent, {"child": child}, {"tenant": TENANT}, probe=probe)
        assert probe.seen == [{}]

    def test_a_grandchild_is_narrowed_by_its_own_declaration_too(self) -> None:
        """Two levels, and the rule is the same one at each boundary.

        The middle document declares nothing, so nothing crosses it — a package
        cannot pass on a key it never asked for. The grandchild therefore gets
        its own default rather than the top run's value, which is what makes a
        package's behaviour a function of its own document and its immediate
        caller's, at any depth.
        """
        probe = Probe()
        grandchild = _document(
            "grandchild",
            context=[{"key": "locale", "type": "string", "label": "L", "default": "de-DE"}],
            probe=True,
        )
        middle = _document("middle", mounts="grandchild")
        parent = _document("parent", context=PARENT_DECLARATION, mounts="middle")
        _run(parent, {"middle": middle, "grandchild": grandchild}, {"tenant": TENANT}, probe=probe)
        assert probe.seen == [{"locale": "de-DE"}]

    def test_a_grandchild_that_declares_a_key_its_parent_also_declares_gets_the_runs_value(
        self,
    ) -> None:
        probe = Probe()
        grandchild = _document("grandchild", context=CHILD_DECLARATION, probe=True)
        middle = _document("middle", context=CHILD_DECLARATION, mounts="grandchild")
        parent = _document("parent", context=PARENT_DECLARATION, mounts="middle")
        _run(parent, {"middle": middle, "grandchild": grandchild}, {"tenant": TENANT}, probe=probe)
        assert probe.seen == [{"locale": "fr-FR"}]


# --------------------------------------------------------------------------- #
# A declared field is never silently `None` — the door 70 built, at the mount.
# --------------------------------------------------------------------------- #


class TestWhatCannotBeSuppliedIsSaidOutLoud:
    """A declared field is never silently `None` — 70's door, at the mount.

    The refusal arrives as **this platform's own sentence on the developer
    channel**, not as a raised exception, because that is what every node
    failure does here: `_error_handler_for` turns any node's exception into a
    failure marker in `outputs` so one bad step does not abort a run, and
    `node_failure_warnings` republishes it as a warning. What matters for this
    ticket is that the child does not run with a required field missing and
    that the sentence names the key and the child — which is the shape 70
    settled and this reuses rather than restates.

    **Knowable earlier than this, and filed rather than smuggled in**: that a
    mount's child requires a key its parent's declaration cannot supply is a
    fact about two documents, so `validate` could say it before any run.
    `organisms-first-class/79`.
    """

    def test_a_required_child_key_the_parent_cannot_supply_is_refused_in_our_words(self) -> None:
        child = _document(
            "child",
            context=[{"key": "caseId", "type": "string", "label": "Case id", "required": True}],
            probe=True,
        )
        parent = _document("parent", context=PARENT_DECLARATION, mounts="child")
        result = _run(parent, {"child": child}, {"tenant": TENANT})
        reason = parse_failure_marker(str(result["outputs"]["m1"]))
        assert reason is not None
        assert "caseId" in reason and "child" in reason

    def test_a_value_of_the_wrong_declared_type_is_refused_at_the_mount(self) -> None:
        """The parent declared `locale` a string; this child declares a number.

        One key, two documents, two meanings — and the child's node reads the
        value, so nothing but a refusal is honest here.
        """
        child = _document(
            "child",
            context=[{"key": "locale", "type": "number", "label": "Locale", "required": True}],
            probe=True,
        )
        parent = _document("parent", context=PARENT_DECLARATION, mounts="child")
        result = _run(parent, {"child": child}, {"tenant": TENANT})
        reason = parse_failure_marker(str(result["outputs"]["m1"]))
        assert reason is not None
        assert "locale" in reason and "number" in reason

    def test_the_probe_inside_such_a_child_never_ran(self) -> None:
        """Refused *before* `invoke`, so no node of the child saw a half-context."""
        probe = Probe()
        child = _document(
            "child",
            context=[{"key": "caseId", "type": "string", "label": "Case id", "required": True}],
            probe=True,
        )
        parent = _document("parent", context=PARENT_DECLARATION, mounts="child")
        _run(parent, {"child": child}, {"tenant": TENANT}, probe=probe)
        assert probe.seen == []


# --------------------------------------------------------------------------- #
# The inverses: everything that must not have changed.
# --------------------------------------------------------------------------- #


class TestNothingElseAboutAMountMoved:
    def test_a_composition_declaring_no_context_anywhere_is_unchanged(self) -> None:
        probe = Probe()
        child = _document("child", probe=True)
        result = _run(_document("parent", mounts="child"), {"child": child}, probe=probe, question="q")
        assert probe.seen == [{}]
        assert _answer(result) == "q"

    def test_the_four_identity_keys_still_cross_and_the_slug_is_still_overridden(self) -> None:
        """`ticket 02`'s single-key override, unchanged by this ticket."""
        seen: dict[str, Any] = {}

        def probe(text: str) -> str:
            from langgraph.config import get_config

            seen.update(get_config().get("configurable") or {})
            return text

        child = _document("child", context=CHILD_DECLARATION, probe=True)
        parent = _document("parent", context=PARENT_DECLARATION, mounts="child")
        runtime = NodeRuntime(
            document_loader={"child": child}.__getitem__, functions={"function.probe": probe}
        )
        graph = WorkflowCompiler().build(parent, RunState, runtime.factory(parent))
        graph.invoke(
            {"question": "q", "messages": [], "attempts": 0, "decisions": {}, "outputs": {}},
            {
                "configurable": {
                    "thread_id": "t1",
                    "session_id": "s1",
                    "workflow_slug": "parent",
                    "user_email": "someone@example.invalid",
                }
            },
            context={"tenant": TENANT},
        )
        assert seen["workflow_slug"] == "child"
        assert seen["thread_id"] == "t1"
        assert seen["session_id"] == "s1"
        assert seen["user_email"] == "someone@example.invalid"
