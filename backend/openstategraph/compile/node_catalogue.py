"""The node/port catalogue, loaded from a generated artifact.

**What this replaces.** `workflow_compiler.py` used to carry a hand-written
Python copy of the TypeScript node catalogue, and its own comment admitted the
duplication (register RC-01). CLAUDE.md's rule is one declaration and generated
consumers; the mirror is now deleted.

**Which side generates.** TypeScript. `src/nodes/**` is where a node type is
declared, where `ports` is a *function of node data*, and where the palette,
canvas, inspector and connection rules read from. Python only ever consumes the
shape. So `src/nodes/portSpecs.ts` emits `port_specs.json` beside this module
and this module loads it.

**Why the artifact is committed.** The wheel must work with no Node.js
installed — an adopter running `load_workflow` has npm nowhere near them. So the
JSON ships inside the package (hatchling includes non-Python files under
`openstategraph/`), and CI regenerates and diffs it so a stale copy fails the
build rather than rotting behind a comment.

A malformed or absent artifact raises rather than degrading to an empty table:
an empty catalogue would not crash the compiler, it would quietly turn every
tool binding into a control-flow edge — the exact silent miswiring this work
exists to prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Bumped in lockstep with `PORT_SPEC_SCHEMA_VERSION` in `src/nodes/portSpecs.ts`.
SCHEMA_VERSION = 2

#: Ships inside the package, not at the repo root: an installed wheel has no
#: repository around it.
ARTIFACT_PATH = Path(__file__).with_name("port_specs.json")

#: Named in every failure message, because "the artifact is stale" without the
#: command is a comment asking a human to remember.
GENERATE_COMMAND = "npm run generate:ports"


class CatalogueError(RuntimeError):
    """The generated catalogue is missing, unreadable or a version we do not know."""


@dataclass(frozen=True)
class PortSpec:
    """What a consumer needs to know about one port.

    `type` and `direction` are what the compiler resolves an edge with; the rest
    is what MCP clients and validators need and used to have to guess. Every
    field after `direction` has a default, so `PortSpec("text", "in")` — the way
    an injected test resolver builds one — keeps working unchanged.

    `max_connections` is `int | None` with `None` meaning unbounded. Never
    `Infinity`: CLAUDE.md forbids a non-finite number in a serialisable field,
    and this one arrives as JSON.
    """

    type: str
    direction: str
    label: str = ""
    required: bool = False
    max_connections: int | None = None
    #: Source port types this port accepts, the editor's port-level widening
    #: already resolved in.
    accepts: tuple[str, ...] = ()


@dataclass(frozen=True)
class DynamicPortGroup:
    """A family of ports a node generates from its own configuration.

    Today there is exactly one: a router's `branch:<slug>` outputs, one per
    configured branch. The generator discovers these by probing the node's own
    `ports()` function rather than by reading a second declaration, so the
    prefix cannot drift from the code that produces the ids.
    """

    prefix: str
    type: str
    direction: str
    max_connections: int | None = None
    accepts: tuple[str, ...] = ()


@dataclass(frozen=True)
class NodeCatalogue:
    """Every node type the editor can register, and how its ports behave."""

    schema_version: int
    #: node type -> port id -> spec. The compiler's `DEFAULT_PORT_SPECS`.
    port_specs: dict[str, dict[str, PortSpec]]
    #: node type -> the port families it generates from config.
    dynamic_ports: dict[str, tuple[DynamicPortGroup, ...]]
    #: Full records, for surfaces that describe rather than compile (MCP).
    nodes: tuple[dict[str, Any], ...]
    port_types: tuple[dict[str, Any], ...]
    #: Data keys a saved document may still carry that no field declares —
    #: today only the Grader's superseded `criteriaMode`, kept as a migration
    #: fallback. Declared in `src/nodes/skillLayer.ts`, emitted here so the
    #: data-key contract can tell a deliberate compatibility read from a field
    #: nobody can write.
    legacy_data_keys: frozenset[str] = frozenset()

    @property
    def node_types(self) -> frozenset[str]:
        return frozenset(self.port_specs)

    @property
    def model_driven(self) -> frozenset[str]:
        """The node types that declare the editor's shared model picker.

        The editor is authoritative, as it is for ports. This exists because
        the two sides had disagreed without anything failing:
        `NodeRuntime._resolve_model(data)` read `data["model"]` for six node
        types while only `agent.llm` shipped the field, so five of them ran
        whichever model the request happened to resolve and no one could say
        otherwise. A wrong model is not a crash — it is a quietly worse answer,
        which is why this needed a test rather than a comment.
        """
        return frozenset(
            str(node["type"]) for node in self.nodes if node.get("drives_model")
        )

    @property
    def accepts_skill(self) -> frozenset[str]:
        """The node types that declare the editor's shared `skill` input port.

        The same guard as `model_driven`, for the same silence: this runtime
        reads `plan.skill_bindings` and composes a wired skill into the prompt
        for five node types, and the editor declared the port on two of them.
        The other three had a compiler ready to read something no canvas could
        wire. `backend/tests/test_skill_layer_contract.py` asserts the two sets
        are equal.
        """
        return frozenset(
            str(node["type"]) for node in self.nodes if node.get("accepts_skill")
        )

    @property
    def field_keys(self) -> dict[str, frozenset[str]]:
        """node type -> every `data` key its editor configuration can write.

        The generalisation of `model_driven` and `accepts_skill`. Both of those
        pin one shared field each, and each exists because that field was read
        by a factory and declared by nobody — a defect that raises nothing,
        because a missing key simply reads as `""` forever. Three shipped
        before this was generalised (the model picker, the worker's rules mode,
        the supervisor's rules). `backend/tests/test_data_key_contract.py`
        asserts every literal key a factory reads appears here.
        """
        return {
            str(node["type"]): frozenset(node.get("field_keys") or ())
            for node in self.nodes
        }


def load_catalogue(path: Path | None = None) -> NodeCatalogue:
    """Reads and validates the generated artifact.

    Injectable `path` so a test can prove the drift gate refuses a corrupted
    file — the gate is worthless if nothing ever exercises the failure.
    """
    source = path or ARTIFACT_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogueError(
            f"The generated node catalogue is missing at {source}. Run `{GENERATE_COMMAND}`."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogueError(
            f"The generated node catalogue at {source} is unreadable ({exc}). "
            f"Do not hand-edit it — run `{GENERATE_COMMAND}`."
        ) from exc

    found = payload.get("schema_version")
    if found != SCHEMA_VERSION:
        raise CatalogueError(
            f"The generated node catalogue at {source} declares schema_version "
            f"{found!r}, but this runtime understands {SCHEMA_VERSION}. "
            f"Run `{GENERATE_COMMAND}`."
        )

    nodes = tuple(payload.get("node_types") or ())
    port_specs: dict[str, dict[str, PortSpec]] = {}
    dynamic: dict[str, tuple[DynamicPortGroup, ...]] = {}
    for node in nodes:
        node_type = node["type"]
        port_specs[node_type] = {
            port["id"]: PortSpec(
                type=port["type"],
                direction=port["direction"],
                label=port.get("label", ""),
                required=bool(port.get("required", False)),
                max_connections=port.get("max_connections"),
                accepts=tuple(port.get("accepts") or ()),
            )
            for port in node.get("ports") or ()
        }
        groups = tuple(
            DynamicPortGroup(
                prefix=group["prefix"],
                type=group["type"],
                direction=group["direction"],
                max_connections=group.get("max_connections"),
                accepts=tuple(group.get("accepts") or ()),
            )
            for group in node.get("dynamic_ports") or ()
        )
        if groups:
            dynamic[node_type] = groups

    return NodeCatalogue(
        schema_version=SCHEMA_VERSION,
        port_specs=port_specs,
        dynamic_ports=dynamic,
        nodes=nodes,
        port_types=tuple(payload.get("port_types") or ()),
        legacy_data_keys=frozenset(payload.get("legacy_data_keys") or ()),
    )


#: Loaded once at import. A module-level failure is the point: a runtime that
#: cannot read its own catalogue must not start and quietly miswire graphs.
CATALOGUE = load_catalogue()

__all__ = [
    "ARTIFACT_PATH",
    "CATALOGUE",
    "GENERATE_COMMAND",
    "SCHEMA_VERSION",
    "CatalogueError",
    "DynamicPortGroup",
    "NodeCatalogue",
    "PortSpec",
    "load_catalogue",
]
