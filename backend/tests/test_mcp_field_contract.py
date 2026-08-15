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
from openstategraph.prebuilt_mcp import MCP_FIELD_KEYS, McpTool

ROOT = Path(__file__).resolve().parents[2]
PORT_SPECS = ROOT / "backend" / "openstategraph" / "compile" / "port_specs.json"
FIELD_SET = ROOT / "src" / "nodes" / "tools" / "mcpServerFields.ts"

#: `StateGraph.add_node` parameters the editor puts on every node. They belong
#: to the workflow, not to any family, so they are not this atom's to mirror.
GRAPH_ASSEMBLY_KEYS = {"maxRetries", "timeoutSeconds"}


def _declared_keys() -> set[str]:
    specs = json.loads(PORT_SPECS.read_text())
    entry = next(item for item in specs["node_types"] if item["type"] == McpTool.node_type)
    return set(entry["field_keys"]) - GRAPH_ASSEMBLY_KEYS


class TestTheCardAndTheToolAgree:
    def test_the_editor_declares_every_key_the_tool_reads(self) -> None:
        missing = set(MCP_FIELD_KEYS) - _declared_keys()
        assert not missing, (
            f"prebuilt_mcp reads {sorted(missing)}, which no field on tool.mcp declares — "
            f"those keys are '' forever, silently."
        )

    def test_the_tool_reads_every_key_the_editor_declares(self) -> None:
        """Asserted in both directions, unlike the general guard.

        A tool card is small enough that a control reaching nothing is a
        defect rather than a legitimate case — there is no equivalent here of
        a worker's `role`, which its *supervisor's* factory reads.
        """
        unread = _declared_keys() - set(MCP_FIELD_KEYS)
        assert not unread, f"tool.mcp declares {sorted(unread)}, which nothing reads."

    def test_the_node_type_is_one_string_in_both_languages(self) -> None:
        assert McpTool.node_type == "tool.mcp"
        known = {item["type"] for item in json.loads(PORT_SPECS.read_text())["node_types"]}
        assert McpTool.node_type in known


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
