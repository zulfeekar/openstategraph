"""The `tool.mcp` card and the `tool.mcp` tool declare the same eight keys.

The general defect this guards is recorded in `test_data_key_contract.py`: a
factory reads `data["x"]`, no field declares `x`, and nothing raises — the key
is `""` forever. That guard covers the *compiler's* factories, which is where
the three shipped instances were. It does not cover a **tool's** `configure()`,
by deliberate design (its docstring says so: a tool node's fields are read by
the tool implementation, not by `node_runtime`).

`tool.mcp` is the first atom for which that exemption is expensive. It reads
six configuration keys, and a misspelling in any of them produces a node that
looks configured and connects to nothing — the exact failure shape, through
the one door the existing guard leaves open. So this test closes it for this
atom, off the generated port table rather than off a hand-kept list.

The second half is the secret-prefix list, which exists in both languages
because both halves validate. A guard that runs in one and not the other is
half a guard, and the missing half is always the one somebody hits.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from openstategraph.config_file import SECRET_VALUE_PREFIXES
from openstategraph.prebuilt_mcp import MCP_NODE_KEYS, MCP_ROW_KEYS, McpTool

ROOT = Path(__file__).resolve().parents[2]
PORT_SPECS = ROOT / "backend" / "openstategraph" / "compile" / "port_specs.json"
FIELD_SET = ROOT / "src" / "nodes" / "tools" / "mcpServerFields.ts"
REGISTRY_CLIENT = ROOT / "src" / "core" / "runtime" / "McpRegistryClient.ts"

#: `StateGraph.add_node` parameters the editor puts on every node. They belong
#: to the workflow, not to any family, so they are not this atom's to mirror.
GRAPH_ASSEMBLY_KEYS = {"maxRetries", "timeoutSeconds"}

#: The card's two read-only blocks. `MCP_FIELD` names them because the schema
#: has to key them; nothing reads them and nothing stores them, so they are
#: neither a node key nor a row key. See the test that pins exactly that.
DISPLAY_ONLY_KEYS = {"mcpGuide", "mcpNote"}


def _declared_keys() -> set[str]:
    specs = json.loads(PORT_SPECS.read_text())
    entry = next(item for item in specs["node_types"] if item["type"] == McpTool.node_type)
    return set(entry["field_keys"]) - GRAPH_ASSEMBLY_KEYS


def _typescript_keys() -> dict[str, str]:
    """`MCP_FIELD` in the editor's own words, read out of the declaration.

    The generated port table carries the node's keys and stops there — a row's
    sub-keys are inside a `repeatable-group` and `defaultsFrom` never sees
    them. Since ticket 04 that is where six of the seven server keys live, so
    the contract reads the factory's own constant rather than losing its grip
    on exactly the keys a misspelling would silence.
    """
    source = FIELD_SET.read_text()
    block = re.search(r"export const MCP_FIELD = \{(.*?)\} as const", source, re.S)
    assert block, "mcpServerFields.ts no longer declares MCP_FIELD"
    return dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))


class TestTheCardAndTheToolAgree:
    def test_the_editor_declares_every_key_the_node_carries(self) -> None:
        missing = set(MCP_NODE_KEYS) - _declared_keys()
        assert not missing, (
            f"prebuilt_mcp reads {sorted(missing)} off a node, which no field on tool.mcp "
            f"declares — those keys are '' forever, silently."
        )

    def test_the_tool_reads_every_key_the_editor_declares(self) -> None:
        """Asserted in both directions, unlike the general guard.

        A tool card is small enough that a control reaching nothing is a
        defect rather than a legitimate case — there is no equivalent here of
        a worker's `role`, which its *supervisor's* factory reads.
        """
        unread = _declared_keys() - set(MCP_NODE_KEYS)
        assert not unread, f"tool.mcp declares {sorted(unread)}, which nothing reads."

    def test_a_server_row_is_spelled_the_same_in_both_languages(self) -> None:
        """The seven keys inside a row, and the panel's flat seven, are one set.

        `configure()` reads them off a row; the app-level panel writes them
        flat; both spellings come from `MCP_FIELD`. A key added on one side
        only would make a control that configures nothing — the defect this
        file exists for, one container deeper.
        """
        declared = set(_typescript_keys().values())
        missing = set(MCP_ROW_KEYS) - declared
        assert not missing, f"prebuilt_mcp reads {sorted(missing)} off a row; MCP_FIELD has no such key."
        # And nothing in the editor's vocabulary that nothing reads —
        # `DISPLAY_ONLY_KEYS` excepted, which is the point of them.
        unread = declared - set(MCP_ROW_KEYS) - set(MCP_NODE_KEYS) - DISPLAY_ONLY_KEYS
        assert not unread, f"MCP_FIELD declares {sorted(unread)}, which nothing reads."

    def test_the_display_blocks_are_read_by_nobody_and_stored_nowhere(self) -> None:
        """The two keys that are deliberately outside the contract above.

        `mcpGuide` and `mcpNote` are `readonly` fields: inspector prose,
        declared on the schema, identical for every node of the type. Until
        production-ready 52 the editor seeded them into each node's `data` and
        saved ~1.5 KB of its own help text into the user's `workflow.json`, so
        they appeared in the generated port table and had to be mirrored here
        to keep the contract green — a mirror of something that was never
        configuration.

        Now they are display on both sides. The assertion is that they are
        *not* in the port table: this is the pin that fails if seeding ever
        comes back, and it is why the exemption above cannot quietly widen.
        """
        assert DISPLAY_ONLY_KEYS <= set(_typescript_keys().values())
        assert not DISPLAY_ONLY_KEYS & _declared_keys()
        assert not DISPLAY_ONLY_KEYS & set(MCP_NODE_KEYS)

    def test_the_node_type_is_one_string_in_both_languages(self) -> None:
        assert McpTool.node_type == "tool.mcp"
        known = {item["type"] for item in json.loads(PORT_SPECS.read_text())["node_types"]}
        assert McpTool.node_type in known


class TestTheThreeVocabulariesDoNotDiverge:
    """The values, not only the keys — framework-packaging ticket 10.

    This file pinned what the fields are *called* and stopped there. The three
    closed sets whose members cross the wire — a transport, an auth kind, a
    status — were two hand-mirrors each, with `mcpPanelSurface.test.ts` holding
    the TypeScript half and `test_prebuilt_mcp.py` the Python half, and nothing
    comparing them. A value only one side knows is the same defect one level
    down from a key only one side knows: a document that stores `http` where
    the runtime expects `streamable_http` looks configured and connects to
    nothing.

    Order is asserted along with membership. For the two dropdowns it is the
    order a developer is offered them in, and `streamable_http` leading is the
    argument `MCP_TRANSPORT_OPTIONS` makes in prose.
    """

    @staticmethod
    def _const_values(source: Path, name: str) -> list[str]:
        block = re.search(rf"export const {name}[^=]*= \[(.*?)\n\];", source.read_text(), re.S)
        assert block, f"{source.name} no longer declares {name}"
        return re.findall(r"'([^']+)'", block.group(1))

    def test_the_extractors_can_actually_fail(self) -> None:
        """The control every pin in this file carries. Two of the three read
        symbols rather than literals, which is one more way to match nothing."""
        assert len(self._resolved(FIELD_SET, "MCP_TRANSPORT_OPTIONS")) == 2
        assert len(self._resolved(FIELD_SET, "MCP_AUTH_OPTIONS")) == 3
        assert len(self._const_values(REGISTRY_CLIENT, "MCP_STATUSES")) == 5

    def test_the_two_transports_are_the_same_two(self) -> None:
        from openstategraph.prebuilt_mcp import TRANSPORTS

        # The card names its own constants (`TRANSPORT_HTTP`), so the values
        # are resolved through the file's own literal declarations rather than
        # re-typed here — which is the point of the atom having them.
        assert self._resolved(FIELD_SET, "MCP_TRANSPORT_OPTIONS") == list(TRANSPORTS)

    def test_the_three_auth_kinds_are_the_same_three(self) -> None:
        from openstategraph.prebuilt_mcp import AUTH_KINDS

        assert self._resolved(FIELD_SET, "MCP_AUTH_OPTIONS") == list(AUTH_KINDS)

    def test_the_five_statuses_are_the_same_five(self) -> None:
        from openstategraph.prebuilt_mcp import MCP_STATUSES

        assert self._const_values(REGISTRY_CLIENT, "MCP_STATUSES") == list(MCP_STATUSES)

    @classmethod
    def _resolved(cls, source: Path, name: str) -> list[str]:
        """Option values, with a named constant looked up in the same file."""
        text = source.read_text()
        out: list[str] = []
        for literal, symbol in re.findall(r"value:\s*(?:'([^']+)'|(\w+))", _block(source, name)):
            if literal:
                out.append(literal)
                continue
            found = re.search(rf"export const {symbol} = '([^']+)'", text)
            assert found, f"{source.name} names {symbol} in {name} and does not declare it"
            out.append(found.group(1))
        return out


def _block(source: Path, name: str) -> str:
    block = re.search(
        rf"export const {name}: readonly FieldOption\[\] = \[(.*?)\n\];",
        source.read_text(),
        re.S,
    )
    assert block, f"{source.name} no longer declares {name}"
    return block.group(1)


class TestTheSecretPrefixesDoNotDiverge:
    def test_both_languages_refuse_the_same_credentials(self) -> None:
        source = FIELD_SET.read_text()
        block = re.search(r"SECRET_VALUE_PREFIXES = \[(.*?)\] as const", source, re.S)
        assert block, "mcpServerFields.ts no longer declares SECRET_VALUE_PREFIXES"
        typescript = tuple(re.findall(r"'((?:[^'\\]|\\.)*)'", block.group(1)))
        assert typescript == SECRET_VALUE_PREFIXES

    def test_a_github_token_is_refused_despite_being_a_legal_variable_name(self) -> None:
        """The case that proves the shape check alone was not enough."""
        from openstategraph.prebuilt_mcp import AUTH_BEARER, McpAuth, resolve_auth_headers

        _headers, problem = resolve_auth_headers(
            McpAuth(kind=AUTH_BEARER, token_env="ghp_aaaaaaaaaaaaaaaaaaaa"), server_name="s"
        )
        assert problem is not None
        assert "ghp_aaaaaaaaaaaaaaaaaaaa" not in problem
