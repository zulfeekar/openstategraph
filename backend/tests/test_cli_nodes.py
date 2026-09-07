"""`openstategraph nodes` — the vocabulary, through the door that had none.

`osg-agent-experience/33`. The sheet's first rule is *read the vocabulary
before composing anything*. Through the MCP door that is `get_node_vocabulary`.
Through the command line the sheet could only send an agent to read
`compile/port_specs.json` inside the installed package — a 7-key generated
document — and a Haiku agent following the sheet never did: it invented a
`systemPrompt` on a classifier that has `rules`/`branches`/`fallback`/
`matchMode`, put a dict where a string goes, and wrote `mssql` into a SQLite
path.

These tests assert on what the terminal prints, never on the shape of
`NodeVocabulary.describe()` — the command is a **renderer** over the same
payload the MCP door publishes, and it must stay one. There is exactly one
reader of `port_specs.json` in this repository's Python and it is the
catalogue; a second one is the drift this command exists to prevent, so
`test_it_renders_the_same_vocabulary_the_mcp_door_publishes` calls both.
"""

from __future__ import annotations

import pytest

from openstategraph import cli


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    code = cli.main(["nodes", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestWithNoArgumentItListsEveryType:
    def test_the_types_a_composing_agent_needs_are_all_there(self, capsys) -> None:
        code, out, _ = _run(capsys)

        assert code == 0
        for node_type in ("agent.llm", "route.classifier", "route.grader", "tool.sql-query"):
            assert node_type in out, f"the list never names {node_type}"

    def test_each_row_carries_the_label_and_a_line_of_prose(self, capsys) -> None:
        _, out, _ = _run(capsys)

        row = next(line for line in out.splitlines() if line.startswith("route.classifier"))
        assert "Router" in row
        assert "branch" in row.lower(), f"no description on the row: {row!r}"

    def test_it_says_how_to_ask_for_one_types_fields(self, capsys) -> None:
        """A list nobody can drill into is a list that gets guessed past."""
        _, out, _ = _run(capsys)

        assert "openstategraph nodes <type>" in out


class TestWithATypeItPrintsTheFieldsAndThePorts:
    """The ticket's own done-when, verbatim: `branches`, `rules`, `fallback`
    and `matchMode` with their kinds."""

    @pytest.mark.parametrize(
        ("key", "kind"),
        [
            ("branches", "repeatable-group"),
            ("rules", "textarea"),
            ("fallback", "text"),
            ("matchMode", "select"),
        ],
    )
    def test_every_field_the_classifier_has_is_printed_with_its_kind(
        self, capsys, key: str, kind: str
    ) -> None:
        code, out, _ = _run(capsys, "route.classifier")

        assert code == 0
        row = next(
            (line for line in out.splitlines() if line.strip().startswith(key)),
            None,
        )
        assert row is not None, f"{key} is absent from the field list"
        assert kind in row, f"{key} printed without its kind: {row!r}"

    def test_a_select_prints_the_values_it_will_accept(self, capsys) -> None:
        """The half a kind alone does not give you. `matchMode` is `select`;
        without its options an agent still has to guess the string.

        Asserted on the line *under* the field rather than anywhere in the
        output: `best` and `all` are ordinary English and both appear in this
        type's hints, so a substring search over the whole page stayed green
        against a build that printed no options at all."""
        _, out, _ = _run(capsys, "route.classifier")

        lines = out.splitlines()
        index = next(i for i, line in enumerate(lines) if line.strip().startswith("matchMode"))
        options = lines[index + 1]
        assert options.strip().startswith("one of:"), f"no option line under matchMode: {options!r}"
        assert "best" in options and "all" in options

    def test_a_required_field_is_marked_and_an_optional_one_is_not(self, capsys) -> None:
        _, out, _ = _run(capsys, "tool.sql-query")

        row = next(line for line in out.splitlines() if line.strip().startswith("database"))
        assert "required" in row

    def test_the_hint_the_editor_shows_is_shown_here_too(self, capsys) -> None:
        _, out, _ = _run(capsys, "route.classifier")

        assert "Applies to the rules typed here" in out

    def test_the_ports_carry_direction_type_and_cardinality(self, capsys) -> None:
        _, out, _ = _run(capsys, "agent.llm")

        ports = out.split("ports:", 1)[1]
        prompt = next(line for line in ports.splitlines() if line.strip().startswith("prompt"))
        assert "in" in prompt and "text" in prompt and "1" in prompt
        tools = next(line for line in ports.splitlines() if line.strip().startswith("tools"))
        assert "unlimited" in tools, f"a null max_connections is a bus, not a blank: {tools!r}"

    def test_a_generated_port_group_is_named_rather_than_left_out(self, capsys) -> None:
        """A classifier's out-ports do not exist until its branches do. Printing
        only the three static in-ports would tell an agent the node has no way
        out — which is the shape of the `32` document's fifteen edges from a
        `result` port the type never declared."""
        _, out, _ = _run(capsys, "route.classifier")

        assert "branch:" in out

    def test_a_branch_groups_cap_is_the_one_the_catalogue_publishes(self, capsys) -> None:
        """`osg-agent-experience/53`. A branch carries **one** edge (`38`), and
        `port_specs.json` has said so since. This line hardcoded `unlimited`,
        so the one door that exists to advise a composing agent gave the exact
        advice that produced `38`: fifteen edges out of a port that refuses the
        second. Asserted against the catalogue in both directions, so neither
        word can be a literal here again."""
        from openstategraph.compile.node_catalogue import CATALOGUE
        from openstategraph.node_report import UNLIMITED

        for node_type in ("route.classifier", "route.check"):
            _, out, _ = _run(capsys, node_type)
            groups = CATALOGUE.dynamic_ports.get(node_type) or ()
            assert groups, f"{node_type} declares no generated port group"
            for group in groups:
                row = next(
                    line
                    for line in out.splitlines()
                    if line.strip().startswith(group.prefix)
                )
                cap = (
                    UNLIMITED
                    if group.max_connections is None
                    else str(group.max_connections)
                )
                assert f"max {cap}" in row, (
                    f"{node_type} {group.prefix} prints {row!r}, "
                    f"but the catalogue says max_connections={group.max_connections}"
                )

    def test_a_branch_takes_one_edge_today_and_the_row_says_so(self, capsys) -> None:
        """The direction the assertion above cannot fail in on its own: if the
        catalogue ever published `null` here, the paired test would agree with
        it and say nothing. This is the fact `38` settled, stated once."""
        from openstategraph.compile.node_catalogue import CATALOGUE

        for node_type in ("route.classifier", "route.check"):
            assert all(
                group.max_connections == 1
                for group in CATALOGUE.dynamic_ports[node_type]
            )
            _, out, _ = _run(capsys, node_type)
            row = next(line for line in out.splitlines() if line.strip().startswith("branch:"))
            assert "max 1" in row and "unlimited" not in row, row

    def test_it_renders_the_same_vocabulary_the_mcp_door_publishes(self, capsys) -> None:
        """One source. If this command ever grows its own reader of
        `port_specs.json`, a type added in the editor reaches one door and not
        the other — which is exactly the drift the generated catalogue exists
        to end."""
        from openstategraph.mcp_server import NodeVocabulary

        _, out, _ = _run(capsys)
        published = {node["type"] for node in NodeVocabulary().describe()["node_types"]}

        printed = {line.split()[0] for line in out.splitlines() if line and not line[0].isspace()}
        assert published <= printed, (
            f"the MCP door publishes types the CLI hides: {published - printed}"
        )


class TestAnUnknownTypeIsAUsageErrorThatNamesTheNeighbours:
    def test_it_exits_two_and_suggests_the_nearest_ids(self, capsys) -> None:
        code, _, err = _run(capsys, "route.classifer")

        assert code == cli.EXIT_USAGE
        assert "route.classifer" in err
        assert "route.classifier" in err, f"no near miss offered: {err!r}"

    def test_a_type_with_no_near_neighbour_still_says_where_to_look(self, capsys) -> None:
        code, _, err = _run(capsys, "zzzzz")

        assert code == cli.EXIT_USAGE
        assert "openstategraph nodes" in err
