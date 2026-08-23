"""Reducers are a named enum, which is the portability rule that was broken.

CLAUDE.md lists four guardrails that "cost nothing now and are expensive to
retrofit". The second is *"Reducers are a named enum, not arbitrary
functions"*, and it was the only one of the four not actually kept:
`merge_decisions`, `keep_max` and `keep_latest_nonempty` were plain functions
bound straight into `Annotated[...]`, with no enum, registry or name→function
map on either side — while `merge_decisions`' own docstring claimed to be "the
`merge` member" of an enum that did not exist (reviews-2026-08-14 ticket 07).

Why it matters more than tidiness: `workflow.json` is the vendor-neutral
layer, the only thing between this project and being a LangGraph front end. A
reducer written as a Python function is unserialisable and unportable in one
move. A name is data.
"""

from __future__ import annotations

import inspect

from openstategraph.compile.reducers import RESET, Reducer, reducer_for


class TestTheEnum:
    def test_a_member_serialises_as_its_own_name(self) -> None:
        # `str`-valued on purpose: this is a data contract, so a member has to
        # survive a JSON round trip with no encoder.
        assert Reducer.MERGE == "merge"
        assert Reducer.MERGE.value == "merge"

    def test_every_member_has_an_implementation(self) -> None:
        for member in Reducer:
            assert callable(reducer_for(member)), member

    def test_the_set_is_small_and_deliberate(self) -> None:
        # Adding a member is a contract change — a name a stored document may
        # carry and a second runtime must implement. The ceiling is the point.
        assert {member.value for member in Reducer} == {
            "merge",
            "merge_rows",
            "max",
            "latest_nonempty",
            "add_messages",
        }


class TestTheImplementations:
    def test_merge_combines_and_clears_on_reset(self) -> None:
        merge = reducer_for(Reducer.MERGE)

        assert merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
        assert merge({"a": 1}, {RESET: "", "b": 2}) == {"b": 2}

    def test_merge_rows_unions_a_repeated_keys_lists_and_clears_on_reset(self) -> None:
        """`production-ready` 106 — MERGE's own docstring says a node's
        *newest* row is the one that counts, which is wrong for a key that
        records what happened rather than what was decided."""
        merge_rows = reducer_for(Reducer.MERGE_ROWS)

        left = {"n1": {"bound": ["a", "b"], "ran": ["a"]}}
        right = {"n1": {"bound": ["a", "b"], "ran": ["b"]}, "n2": {"bound": [], "ran": []}}
        merged = merge_rows(left, right)
        # Both laps' tools survive — a plain {**left, **right} would have
        # dropped "a" the moment n1's row appeared on the right.
        assert merged["n1"]["ran"] == ["a", "b"]
        assert merged["n2"] == {"bound": [], "ran": []}

        # A field absent from both rows stays absent, not `[]` — `tool_report`
        # never writes `queried` when nothing was sent, and a present empty
        # list is a different claim from no claim at all.
        assert "queried" not in merge_rows(left, right)["n1"]

        assert merge_rows(left, {RESET: "", "n1": {"bound": ["a"], "ran": []}}) == {
            "n1": {"bound": ["a"], "ran": []}
        }

    def test_max_grows_and_zeroes_on_a_negative_write(self) -> None:
        keep_max = reducer_for(Reducer.MAX)

        assert keep_max(2, 1) == 2
        # The numeric spelling of RESET — this channel stays int end to end.
        assert keep_max(3, -1) == 0

    def test_latest_nonempty_refuses_an_empty_overwrite(self) -> None:
        latest = reducer_for(Reducer.LATEST_NONEMPTY)

        assert latest("kept", "") == "kept"
        assert latest("kept", "newer") == "newer"
        assert latest("kept", RESET) == ""


class TestNothingBindsAnAnonymousReducer:
    """The guard, and the reason this file is not just three unit tests.

    Fixing the three that existed is worth little if the fourth is written next
    month — which is exactly what happened to the docstring that described an
    enum nobody had built.
    """

    def test_run_state_declares_its_reducers_by_name(self) -> None:
        from openstategraph.compile import node_runtime

        source = inspect.getsource(node_runtime.RunState)

        # Every `Annotated[...]` in the state schema resolves through
        # `reducer_for`, so a stored document could name what it uses.
        for line in source.splitlines():
            if "Annotated[" not in line:
                continue
            assert "reducer_for(Reducer." in line, line.strip()


class TestTheOtherSideIsNotNeededYet:
    """"Both sides with a drift test" — and why there is no TypeScript enum.

    Ticket 07 asked for the enum "on both sides". The urgency it gave was
    about the **document**: *"every stored workflow that gains a reducer
    reference before the enum exists is a document a second runtime cannot
    read."*

    No stored workflow has one. `RunState` is compiler-side only —
    `workflow.json`, `schema.py` and `src/core/` do not mention a reducer
    anywhere, so nothing in TypeScript has a reducer name to hold. Writing
    the mirror now would produce exactly what CLAUDE.md's DRY rule forbids:
    a hand-written TypeScript mirror of a Python contract, with no consumer
    and nothing pinning the two together.

    So the second side is a **tripwire** rather than a mirror. The moment a
    reducer name reaches the document contract, this fails and says what to
    build — which is the protection the ticket actually asked for, at the
    moment it starts being needed rather than a year before.
    """

    def test_no_reducer_name_has_reached_the_document_contract(self) -> None:
        """Checked in schema *positions*, never by grepping for the word.

        The first version of this grepped `docs/openapi.json` for "reducer"
        and fired on the SSE endpoint's own prose, which explains that the
        stream folds updates with the same reducers `RunState` declares. A
        tripwire that trips on its own documentation is a tripwire someone
        deletes — the same crudeness that made the `contractDrift` pin fire on
        a query suffix.

        So: property names, enum values and `$defs` keys, which is where a
        reducer would have to appear to reach a stored document. Prose is
        prose.
        """
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]

        def schema_names(node: object) -> list[str]:
            """Every name a document could be validated against."""
            found: list[str] = []
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in {"properties", "$defs", "definitions"} and isinstance(value, dict):
                        found.extend(value)
                    if key == "enum" and isinstance(value, list):
                        found.extend(str(entry) for entry in value)
                    found.extend(schema_names(value))
            elif isinstance(node, list):
                for entry in node:
                    found.extend(schema_names(entry))
            return found

        published = json.loads((root / "docs" / "openapi.json").read_text())
        in_contract = [name for name in schema_names(published) if "reducer" in name.lower()]

        # `schema.py` validates the document itself; a reducer would arrive
        # there as a quoted key, not as a word in a comment.
        validator = root / "backend" / "openstategraph" / "schema.py"
        quoted = [
            line.strip()
            for line in validator.read_text().splitlines()
            if '"reducer' in line.lower() or "'reducer" in line.lower()
        ]

        assert not in_contract and not quoted, (
            f"A reducer name reached the document contract ({in_contract or quoted}), "
            "so a stored document can carry one. Build the TypeScript `Reducer` enum "
            "mirroring `openstategraph.compile.reducers.Reducer`, pin the two with a "
            "drift test (docs/decisions/typescript-runtime-types.md records why a "
            "generator was rejected), and delete this test — reviews-2026-08-14 "
            "ticket 07."
        )
