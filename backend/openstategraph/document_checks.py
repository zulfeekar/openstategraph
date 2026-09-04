"""What a document says about itself, checked against what its types declare.

`osg-agent-experience/32`. `validate` answered VALID to a nineteen-node
workflow in which the router had been configured through a key it does not
have, had no branches, and fanned fifteen edges out of a port it does not
declare; sixteen agents held a dict where a paragraph goes; and a *Database
file* held the word `mssql`. Every one of those was knowable from
`compile/port_specs.json`, which the editor already generates and this runtime
already loads — nothing here asks a model, opens a network connection or runs
a graph.

**Findings, not exceptions.** `validation.validate_document` promises a caller
decides what a finding means, and this module keeps that promise: it returns a
list, and an unreadable document produces fewer findings rather than a
traceback. A checker that raises on the document it was written to describe is
a checker somebody wraps in `try`.

**Checks register; this module is not edited to add one.** CLAUDE.md's **O**:
`register_document_check` appends to `DOCUMENT_CHECKS`, and each check answers
about one property of one context. The next one due is
`osg-agent-experience/38` — two edges leaving one conditional branch, of which
the compiled plan keeps one — which needs the same nodes, the same edges and
the same catalogue, and so needs no new machinery here.

Six of them are defined in this module, beside the registry they register into.
`test_a_dispatch_table_does_not_hold_its_targets.py` does not see that — it
looks for `registry.register(key, target)`, and a decorator has no such pair —
so the claim is made here rather than left to a census that cannot check it:
these six are one reason to change, in the sense that module's docstring grants
`compile/reducers.py` its four named reducers. They are the *same* question
asked of six properties, they share `_typed_nodes` and one skip rule, and a
seventh registers from wherever it is written.

**Where it stops.** These checks describe *this* document against *this*
build's catalogue. A node type the catalogue has no field schema for is
skipped whole, exactly as `workflow_compiler.data_key_findings` skips it and
for the same reason: `<slug>/tools.QueryTool` and a package's `functions/` are
minted from Python, have no static schema, and pretending otherwise is a
false-positive avalanche over the workflow-scoped types CLAUDE.md sanctions.
The skip is not silent — `ValidateWorkflowTool` already names such a node.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from openstategraph.compile.node_catalogue import CATALOGUE, FieldSpec


class FindingClass(str, Enum):
    """A way a document disagrees with what its own node types declare.

    `str`-valued for `Finding`'s reason: a member survives a JSON round trip
    with no encoder, so a class can cross the run/stream seam as data. Spelled
    with hyphens because these names are read by people in a terminal.
    """

    #: A key under `data` that the node type declares no field for.
    UNKNOWN_FIELD = "unknown-field"
    #: A value whose JSON type is not the one its field's kind takes — a dict
    #: in a paragraph, a string where a number goes.
    WRONG_KIND = "wrong-kind"
    #: A `select` value outside the list the catalogue publishes for it.
    NOT_AN_OPTION = "not-an-option"
    #: A path-valued field naming no file under its declared root.
    MISSING_FILE = "missing-file"
    #: A node whose outputs are entirely config-generated, wired onward, with
    #: no configuration to generate them from.
    NO_BRANCHES = "no-branches"
    #: An edge naming a port the node's type does not declare, in or out.
    UNKNOWN_PORT = "unknown-port"


@dataclass(frozen=True)
class DocumentFinding:
    """One disagreement: its class, what it is about, and the sentence.

    `subject` is `<node id>.<field or port>` (or the bare node id where the
    node itself is the subject), so a caller can group, count and de-duplicate
    without parsing the sentence — which is the mistake
    `validation.validate_document` records about report scraping one layer up.
    """

    kind: FindingClass
    subject: str
    message: str


@dataclass(frozen=True)
class CheckContext:
    """Everything a check may look at, resolved once.

    `workflows_root` is where a path-valued field resolves from, and it is
    `None` when the caller has no filesystem to answer about — a document
    posted to the stateless MCP door, which holds no workflow library at all.
    A check that needs the disk asks for it and returns nothing without it.

    **The precedent is in `validation.py` and it was learned the same way.**
    `unresolved_mounts` and `unresolved_tool_bindings` are deliberately outside
    `validate_document` because "is it there" needs a root a document does not
    carry. Resolving against the *ambient* root instead is not a smaller
    version of that answer, it is a different question: it accused
    `examples/sql-qa` — a correct document, VALID from the CLI — of pointing at
    a database that does not exist, because the example is not copied into this
    checkout's `workflows/`.
    """

    document: Mapping[str, Any]
    workflows_root: Path | None
    #: node id -> the node record, annotations included.
    nodes: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def schema_for(self, node_type: str) -> dict[str, FieldSpec] | None:
        """This build's field schema for a type, or `None` if it has none."""
        return CATALOGUE.field_schema.get(node_type)


#: The checks, in report order. Appended to by `register_document_check`.
DOCUMENT_CHECKS: list[Callable[[CheckContext], Iterable[DocumentFinding]]] = []


def register_document_check(
    check: Callable[[CheckContext], Iterable[DocumentFinding]],
) -> Callable[[CheckContext], Iterable[DocumentFinding]]:
    """Registers one check. The extension point, so the engine is never edited."""
    DOCUMENT_CHECKS.append(check)
    return check


def document_findings(
    document: Mapping[str, Any],
    *,
    workflows_root: Path | None = None,
) -> list[DocumentFinding]:
    """Every finding in `document`, in registration order.

    `workflows_root` is the directory a path-valued field resolves against —
    a package's parent when there is a package. Omit it and the checks that
    need the disk do not run; see `CheckContext`.
    """
    nested = document.get("document")
    inner: Mapping[str, Any] = nested if isinstance(nested, dict) else document
    nodes = {
        str(node.get("id") or ""): node
        for node in (inner.get("nodes") or [])
        if isinstance(node, dict)
    }
    context = CheckContext(
        document=inner,
        workflows_root=workflows_root,
        nodes=nodes,
    )
    findings: list[DocumentFinding] = []
    seen: set[tuple[FindingClass, str]] = set()
    for check in DOCUMENT_CHECKS:
        for finding in check(context):
            key = (finding.kind, finding.subject)
            if key in seen:
                continue
            # One thing to fix is one finding however many times the document
            # repeats it — `unresolved_mounts`' rule, and the fixture is why it
            # is needed here: thirty edges leave two ports that do not exist,
            # and thirty identical sentences is a list nobody reads to the end.
            seen.add(key)
            findings.append(finding)
    return findings


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #

#: What each field kind's value is, as JSON. A kind absent from this table is
#: not type-checked, which is deliberate: `readonly` is display and never data
#: (production-ready 52), and `file` writes its content to a second key whose
#: shape belongs to the node.
#:
#: **The scalar kinds take a number as well as a string, and that is a
#: narrowing this ticket made under evidence rather than a looseness it
#: inherited.** `examples/sql-qa` writes `"maxRows": 50` into a `text` field —
#: a control can only produce `"50"`, a hand-written document reasonably holds
#: `50`, and every reader in this runtime spells it `int(str(value).strip())`,
#: so the value is read exactly as written. Refusing it would have failed a
#: shipped example over nothing. What no reader survives is a **container
#: where a scalar goes**, which is the defect this check was written for:
#: sixteen agents whose paragraph of rules was a `{"type": …, "content": …}`
#: dict, read as its own Python repr and never as a prompt.
_KIND_TYPES: dict[str, tuple[tuple[type, ...], str]] = {
    "text": ((str, int, float), "a line of text"),
    "textarea": ((str, int, float), "a paragraph of text"),
    "select": ((str,), "one of its listed values"),
    "combobox": ((str, int, float), "a line of text"),
    "slider": ((int, float), "a number"),
    "number": ((int, float), "a number"),
    "toggle": ((bool,), "true or false"),
    "repeatable-group": ((list,), "a list of rows"),
}


def _typed_nodes(context: CheckContext) -> Iterable[tuple[str, str, dict[str, Any]]]:
    """`(node id, type, data)` for every node this build can check.

    A type with no published field schema is skipped here — see the module
    docstring. `data` is always a dict, so a check below never re-asks.
    """
    for node_id, node in context.nodes.items():
        node_type = str(node.get("type") or "")
        if context.schema_for(node_type) is None:
            continue
        raw = node.get("data")
        yield node_id, node_type, raw if isinstance(raw, dict) else {}


@register_document_check
def unknown_fields(context: CheckContext) -> Iterable[DocumentFinding]:
    """A `data` key no field on that node type declares.

    **This used to be an advisory that left the document VALID**, decided
    2026-08-24 (`launch-readiness/24`) on the argument that the key might
    belong to a newer field or a plugin's, so refusing it would break a working
    document on a guess about intent. `osg-agent-experience/32` is the evidence
    that reversed it: the key was `systemPrompt` on a `route.classifier`, it
    carried the router's *entire* configuration, the document did not work at
    all, and the tool said VALID. The generous reading cost more than it saved,
    so the class is a finding now and the sentence says what to do about it.

    `legacy_data_keys` still passes — a key the editor deliberately reads for
    migration is not an unknown one.
    """
    legacy = CATALOGUE.legacy_data_keys
    for node_id, node_type, data in _typed_nodes(context):
        declared = CATALOGUE.field_keys.get(node_type, frozenset()) | legacy
        for key in sorted(data):
            if key in declared:
                continue
            known = ", ".join(sorted(CATALOGUE.field_keys.get(node_type, frozenset()))) or "none"
            yield DocumentFinding(
                FindingClass.UNKNOWN_FIELD,
                f"{node_id}.{key}",
                f'Node "{node_id}" ({node_type}) sets "{key}", which no field on this '
                f"node type declares, so nothing reads it. Its fields are: {known}.",
            )


@register_document_check
def wrong_kinds(context: CheckContext) -> Iterable[DocumentFinding]:
    """A value whose JSON type is not the one the field's kind takes.

    `null` is skipped: an absent value is `required`'s question, already
    answered by `workflow_compiler.data_key_findings`, and answering it twice
    in two vocabularies is how a reader learns to skim a list.

    `bool` is excluded from the numeric kinds explicitly, because Python says
    `isinstance(True, int)` and a toggle in a slider is a real mistake.
    """
    for node_id, node_type, data in _typed_nodes(context):
        schema = context.schema_for(node_type) or {}
        for key in sorted(data):
            spec = schema.get(key)
            value = data[key]
            if spec is None or value is None:
                continue
            if spec.json_value and isinstance(value, (dict, list, str)):
                # The field says its value is JSON, in either of the two
                # shapes a document legitimately holds it in.
                continue
            expected = _KIND_TYPES.get(spec.kind)
            if expected is None:
                continue
            types, described = expected
            if isinstance(value, types) and not (
                isinstance(value, bool) and bool not in types
            ):
                continue
            yield DocumentFinding(
                FindingClass.WRONG_KIND,
                f"{node_id}.{key}",
                f'Node "{node_id}" ({node_type}) sets "{key}" to '
                f"{type(value).__name__}, but that field is a {spec.kind} and takes "
                f"{described}. The value is not read as written.",
            )


@register_document_check
def values_outside_their_options(context: CheckContext) -> Iterable[DocumentFinding]:
    """A `select` value the catalogue does not list.

    Narrow on three axes, each of which would otherwise refuse a valid
    document:

    - **`select` only.** A `combobox` exists so somebody can type what does not
      exist yet — mounting a package before building it is a real way to work
      (`say-it-on-the-surface/03`) — so its list is a suggestion, not a gate.
    - **A published list only.** `FieldSpec.options` is `None` when the list is
      a function of runtime state (which providers hold credentials, what is on
      disk). `None` means *not knowable here*; it never means *nothing is
      permitted*.
    - **A value only.** Empty is unset, which is `required`'s question.
    """
    for node_id, node_type, data in _typed_nodes(context):
        schema = context.schema_for(node_type) or {}
        for key in sorted(data):
            spec = schema.get(key)
            value = data[key]
            if spec is None or spec.kind != "select" or spec.options is None:
                continue
            if not isinstance(value, str) or not value:
                continue
            if value in spec.options:
                continue
            listed = ", ".join(repr(option) for option in spec.options)
            yield DocumentFinding(
                FindingClass.NOT_AN_OPTION,
                f"{node_id}.{key}",
                f'Node "{node_id}" ({node_type}) sets "{key}" to {value!r}, which is '
                f"not one of its values ({listed}) — the node falls back to its "
                "default, so the choice in the document is not the one that runs.",
            )


@register_document_check
def missing_files(context: CheckContext) -> Iterable[DocumentFinding]:
    """A path-valued field naming no file under its declared root.

    The field says it is a path (`FieldSchemaBase.pathRoot`); this asks the
    disk. Containment is part of the answer and not an extra rule: a value that
    resolves outside the root is not a file this product will open, so
    `../../etc/passwd` is *missing* here exactly as it is at run time — the
    same two steps `prebuilt_sql._resolve_database` takes, asked a run earlier.

    An empty value is `required`'s question, not this one. And with no root to
    ask about, this check reports nothing at all rather than guessing at one —
    `CheckContext` carries the reason.
    """
    if context.workflows_root is None:
        return
    root = context.workflows_root.resolve()
    for node_id, node_type, data in _typed_nodes(context):
        schema = context.schema_for(node_type) or {}
        for key in sorted(data):
            spec = schema.get(key)
            value = data[key]
            if spec is None or not spec.path_root or not isinstance(value, str):
                continue
            if not value.strip():
                continue
            candidate = (root / value.strip()).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                inside = False
            else:
                inside = candidate.is_file()
            if inside:
                continue
            yield DocumentFinding(
                FindingClass.MISSING_FILE,
                f"{node_id}.{key}",
                f'Node "{node_id}" ({node_type}) points "{spec.label or key}" at '
                f"{value!r}, which is not a file inside {root}. Every call the node "
                "makes will refuse, and the run will answer without it.",
            )


@register_document_check
def routers_with_nothing_to_route_to(context: CheckContext) -> Iterable[DocumentFinding]:
    """A node wired onward whose only outputs are ones its config generates.

    Derived from the catalogue rather than named: the condition is a type with
    **no static out ports** and a dynamic out-port group, which today is
    `route.classifier` and tomorrow is whatever else is drawn that way. Such a
    node with no rows in its own `repeatable-group` field produces no ports at
    all, so every edge drawn from it points at a port that does not exist and
    the decision the node was placed to make is not in the document.

    Reported when it is wired onward, because that is when it costs something:
    a classifier parked on a canvas mid-edit is a normal state and a finding
    about it is noise.
    """
    catalogue = {str(node["type"]): node for node in CATALOGUE.nodes}
    sources = {
        str((edge.get("source") or {}).get("nodeId") or "")
        for edge in (context.document.get("edges") or [])
        if isinstance(edge, dict)
    }
    for node_id, node_type, data in _typed_nodes(context):
        record = catalogue.get(node_type)
        if record is None or node_id not in sources:
            continue
        if any(port.get("direction") == "out" for port in record.get("ports") or ()):
            continue
        if not any(group.get("direction") == "out" for group in record.get("dynamic_ports") or ()):
            continue
        schema = context.schema_for(node_type) or {}
        rows = [key for key, spec in schema.items() if spec.kind == "repeatable-group"]
        if any(isinstance(data.get(key), list) and data[key] for key in rows):
            continue
        named = " or ".join(f'"{key}"' for key in sorted(rows)) or "its rows"
        yield DocumentFinding(
            FindingClass.NO_BRANCHES,
            node_id,
            f'Node "{node_id}" ({node_type}) has edges leaving it but nothing in '
            f"{named}, and every output it has is one of those rows. It cannot "
            "choose between the paths drawn from it.",
        )


@register_document_check
def unknown_ports(context: CheckContext) -> Iterable[DocumentFinding]:
    """An edge naming a port its node's type does not declare.

    Added 2026-09-05 from the second attempt on the same concept: thirty of the
    fixture's forty-seven edges leave a port called `result` on two types that
    have no such port — a classifier's outputs are `branch:<row id>` and the
    SQL tool's is `tool` — and the verdict was VALID.

    A port matching a dynamic group's prefix passes. Whether that *row* exists
    is a different question with a different answer, and it is not asked here:
    the compiler resolves a branch destination by name, so an id nothing
    matches is a routing defect rather than a shape defect. Recorded as a gap
    rather than half-answered.
    """
    for edge in context.document.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        for side, direction in (("source", "out"), ("target", "in")):
            end = edge.get(side)
            if not isinstance(end, dict):
                continue
            node_id = str(end.get("nodeId") or "")
            port_id = str(end.get("portId") or "")
            node = context.nodes.get(node_id)
            if node is None or not port_id:
                continue
            node_type = str(node.get("type") or "")
            record = next(
                (n for n in CATALOGUE.nodes if str(n["type"]) == node_type),
                None,
            )
            if record is None:
                continue
            declared = {
                str(port["id"])
                for port in record.get("ports") or ()
                if port.get("direction") == direction
            }
            if port_id in declared:
                continue
            prefixes = [
                str(group.get("prefix") or "")
                for group in record.get("dynamic_ports") or ()
                if group.get("direction") == direction and group.get("prefix")
            ]
            if any(port_id.startswith(prefix) for prefix in prefixes):
                continue
            listed = ", ".join(sorted(declared)) or "none"
            grown = "".join(f", or one beginning {prefix!r}" for prefix in sorted(prefixes))
            yield DocumentFinding(
                FindingClass.UNKNOWN_PORT,
                f"{node_id}.{port_id}",
                f'An edge uses port "{port_id}" on node "{node_id}" ({node_type}), '
                f"which declares no such {direction} port. Its {direction} ports are: "
                f"{listed}{grown}.",
            )


__all__ = [
    "DOCUMENT_CHECKS",
    "CheckContext",
    "DocumentFinding",
    "FindingClass",
    "document_findings",
    "register_document_check",
]
