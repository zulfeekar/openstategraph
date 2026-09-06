"""One tool-surface condition gates both disclosure and offload —
`launch-readiness/111` (carrying the open half of `101` and `102`).

`101` built `build_skills_middleware` and `102` built `OffloadMiddleware`, and
neither was ever contributed by the compiler. This file is written against the
defect that wiring them *carelessly* produces, which the ticket names in one
sentence:

    Offloading hands the model a pointer to a file. An agent whose tool
    surface has no `read_file`/`grep` can no more follow that pointer than it
    can open a disclosed skill. Wiring either without the check produces an
    agent holding a reference it cannot dereference.

So the assertions below are **recall checks**, not kwarg checks. Progressive
disclosure that silently never opens a skill and flat injection are two states
with one visible output — a plausible answer — which is this project's most
expensive recurring defect shape (`docs/decisions/deep-agent-slots.md` measured
`skills=` loading a real directory into `(No skills available)` with no error
anywhere). A test that asserts "the middleware was contributed" is exactly the
test that would pass against that silent nothing.

Every model here is a fake. What is proved is what the compiler assembles and
what the agent's own tools return when the model asks for them — never how a
real model decides to ask.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

pytest.importorskip("deepagents")

from langchain.tools import tool

from openstategraph.abc.agent import AbstractAgentNode
from openstategraph.abc.deep_tier_offload import (
    DEEP_TIER_FILE_TOOLS,
    plan_disclosure,
    surface_can_dereference,
)
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan

from conftest import drive_node

SKILL_BODY_MARKER = "OPEN-THE-ENVELOPE-7412"
#: Big enough to be worth disclosing. Disclosure has a break-even — the
#: library's own skills instructions are 1,857 bytes before a single skill is
#: listed — and a body smaller than that costs more to disclose than to inline.
BIG_SKILL_BODY = SKILL_BODY_MARKER + "\n" + ("one instruction line\n" * 200)
BIG_RESULT_MARKER = "ROW-COUNT-IS-88371"


def _package(tmp_path, *, skills: dict[str, str] | None = None):
    """A workflow package laid out the way this project lays them out.

    `skills/*.md` — flat files with frontmatter, which is what
    `discover_skills` globs and what every shipped package carries. Note the
    layout mismatch this exercises: `SkillsMiddleware` reads
    `<source>/<name>/SKILL.md` directories, so the compiler has to *project*
    the package's own layout rather than point the library at it.
    """
    pkg = tmp_path / "pkg"
    (pkg / "skills").mkdir(parents=True)
    for name, body in (skills or {"greet": BIG_SKILL_BODY}).items():
        (pkg / "skills" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: How to greet a customer properly.\n"
            f"---\n\n{body}\n"
        )
    return pkg


# --------------------------------------------------------------------------- #
# The condition itself.
# --------------------------------------------------------------------------- #


class TestTheOneCondition:
    def test_a_surface_with_no_file_reader_cannot_dereference(self) -> None:
        assert not surface_can_dereference(("query_rows", "send_email"), shares_backend=True)

    def test_a_surface_with_a_file_reader_it_does_not_share_cannot_either(self) -> None:
        """The half a naive adoption drops.

        A wired tool called `read_file` reads *its own* store. A pointer into
        the store this seam writes to is not dereferenceable through it, so a
        name match alone is not the condition.
        """
        assert not surface_can_dereference(("read_file", "grep"), shares_backend=False)

    def test_the_deep_tiers_own_file_tools_satisfy_it(self) -> None:
        assert "read_file" in DEEP_TIER_FILE_TOOLS
        assert "grep" in DEEP_TIER_FILE_TOOLS
        assert surface_can_dereference(DEEP_TIER_FILE_TOOLS, shares_backend=True)


class TestOnePlanGovernsBoth:
    def test_neither_middleware_is_contributed_without_the_surface(self, tmp_path) -> None:
        plan = plan_disclosure(
            package_dir=_package(tmp_path),
            tool_surface=("query_rows",),
            shares_backend=False,
        )
        assert plan.contributions == {}
        assert plan.backend is None
        assert plan.flat_injection is True
        assert plan.reason

    def test_both_middlewares_are_contributed_with_it(self, tmp_path) -> None:
        plan = plan_disclosure(
            package_dir=_package(tmp_path),
            tool_surface=DEEP_TIER_FILE_TOOLS,
            shares_backend=True,
            offload_prefixes=("query_rows",),
        )
        assert set(plan.contributions) == {"skills", "filesystem"}
        assert plan.backend is not None
        assert plan.flat_injection is False

    def test_they_flatten_in_the_reserved_order_skills_before_filesystem(
        self, tmp_path
    ) -> None:
        from openstategraph.abc.middleware import MiddlewareSlotTable

        plan = plan_disclosure(
            package_dir=_package(tmp_path),
            tool_surface=DEEP_TIER_FILE_TOOLS,
            shares_backend=True,
        )
        table = MiddlewareSlotTable(order=AbstractAgentNode.SLOT_ORDER)
        table.merge(dict(plan.contributions))
        flat = table.flatten()
        assert flat.index(plan.contributions["skills"]) < flat.index(
            plan.contributions["filesystem"]
        )

    def test_a_skill_with_no_description_is_never_disclosed(self, tmp_path) -> None:
        """Measured, not assumed — and it changed the design.

        `SkillsMiddleware` requires `name` **and** `description` and silently
        skips a file with neither. Two of the three skills this repository
        ships (`workflows/workflow-architect/skills/*.md`) have no frontmatter
        at all, so disclosing a package wholesale would have deleted them from
        the prompt: no body, and no line saying they exist. Disclosure is
        therefore decided per skill, and the undisclosable ones stay flat.
        """
        pkg = tmp_path / "nodesc"
        (pkg / "skills").mkdir(parents=True)
        (pkg / "skills" / "grammar.md").write_text(BIG_SKILL_BODY)
        plan = plan_disclosure(
            package_dir=pkg, tool_surface=DEEP_TIER_FILE_TOOLS, shares_backend=True
        )
        assert plan.disclosed == ()
        assert plan.flat_injection is True

    def test_a_skill_too_small_to_pay_for_disclosure_stays_inline(
        self, tmp_path
    ) -> None:
        """The break-even, and it is a real package rather than a hypothesis.

        `workflows/concierge` carries one 1,970-byte skill; disclosing it made
        the system prompt **134 bytes larger**, because the library's skills
        instructions cost 1,857 bytes before a single skill is listed. A change
        filed to shrink the prompt must not enlarge it for the smallest package
        we ship.
        """
        plan = plan_disclosure(
            package_dir=_package(tmp_path, skills={"tiny": "one short line"}),
            tool_surface=DEEP_TIER_FILE_TOOLS,
            shares_backend=True,
        )
        assert plan.disclosed == ()
        # Offloading is unaffected: the two are gated together, sized apart.
        assert set(plan.contributions) == {"filesystem"}

    def test_a_package_with_no_skills_still_offloads(self, tmp_path) -> None:
        """The two are gated together and *filled* independently.

        Offloading needs no skills directory; a package without one must not
        lose it.
        """
        bare = tmp_path / "bare"
        bare.mkdir()
        plan = plan_disclosure(
            package_dir=bare, tool_surface=DEEP_TIER_FILE_TOOLS, shares_backend=True
        )
        assert set(plan.contributions) == {"filesystem"}
        # Nothing was disclosed, so nothing was withheld from the prompt.
        assert plan.flat_injection is True

    def test_the_result_not_raise_promise_survives_the_wiring(self, tmp_path) -> None:
        """`102`'s finding, re-asserted on the contributed instance.

        `FilesystemBackend._resolve_path` raises `ValueError` on traversal and
        `write` does not catch it. The middleware this plan contributes must
        still hand back a recoverable message rather than kill the run.
        """
        from langchain_core.messages import ToolMessage
        from types import SimpleNamespace

        plan = plan_disclosure(
            package_dir=_package(tmp_path),
            tool_surface=DEEP_TIER_FILE_TOOLS,
            shares_backend=True,
            offload_prefixes=("query_rows",),
            threshold_chars=10,
        )
        offload = plan.contributions["filesystem"]
        offload._path_for = lambda request: "../../etc/passwd"
        big = ToolMessage(content="z" * 500, tool_call_id="c1")
        request = SimpleNamespace(tool_call={"name": "query_rows", "id": "c1"})
        assert offload.wrap_tool_call(request, lambda _r: big) is big


# --------------------------------------------------------------------------- #
# The compiler wiring, and the two recall checks.
# --------------------------------------------------------------------------- #


def _reply(message: AIMessage) -> ChatResult:
    return ChatResult(generations=[ChatGeneration(message=message)])


class Recorder(GenericFakeChatModel):
    """Records every turn it is handed, and drives one scripted tool loop."""

    seen: list[list[tuple[str, str]]] = []

    def __init__(self) -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "seen", [])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "Recorder":
        return self

    def _turn(self, messages: Any) -> list[tuple[str, str]]:
        turn = [(type(m).__name__, str(m.content)) for m in messages]
        self.seen.append(turn)
        return turn

    @property
    def first_system_prompt(self) -> str:
        return "\n".join(c for kind, c in self.seen[0] if kind == "SystemMessage")

    @property
    def tool_results(self) -> list[str]:
        """Every tool result the model held on its **last** turn.

        The last turn, not every turn: each turn is the whole message list, so
        summing across them counts one `ToolMessage` once per turn that
        followed it.
        """
        return [c for kind, c in self.seen[-1] if kind == "ToolMessage"]


class SkillReader(Recorder):
    """Reads the one path the skills list advertises, then answers.

    This is the recall check `101` asked for, made deterministic: a real model
    decides *whether* to open a skill, and that decision is not something a
    test can assert. What a test can assert — and what silently fails today —
    is that the prompt advertises a path and that `read_file` on that path
    returns the body.
    """

    def _generate(self, messages: Any, *args: Any, **kwargs: Any) -> ChatResult:
        turn = self._turn(messages)
        if any(kind == "ToolMessage" for kind, _ in turn):
            return _reply(AIMessage(content="done"))
        text = "\n".join(c for _, c in turn)
        match = re.search(r"(/skills/[\w./-]*SKILL\.md)", text)
        if not match:
            return _reply(AIMessage(content="NO SKILL PATH IN MY PROMPT"))
        return _reply(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": match.group(1), "limit": 1000},
                        "id": "call-skill",
                    }
                ],
            )
        )


_CALLS: list[str] = []


@tool
def query_rows(sql: str) -> str:
    """Run a query and return its rows."""
    _CALLS.append(sql)
    return f"{BIG_RESULT_MARKER}\n" + ("filler row\n" * 4000)


class OffloadRetriever(Recorder):
    """Sees the rows whole, works on, then follows the pointer they became.

    Rewritten for `launch-readiness/162`. It used to look for a pointer on the
    turn the result arrived, which is the defect that ticket is about: the
    first sight is now the rows themselves, and the pointer appears on the
    next turn, once the model has answered on them. The recall claim `102`
    cared about is unchanged and is still asserted — the data comes back
    through the file, never through a second call to the tool.
    """

    def _generate(self, messages: Any, *args: Any, **kwargs: Any) -> ChatResult:
        turn = self._turn(messages)
        results = [c for kind, c in turn if kind == "ToolMessage"]
        if not results:
            return _reply(
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "query_rows", "args": {"sql": "select 1"}, "id": "c1"}
                    ],
                )
            )
        if len(results) == 1:
            if BIG_RESULT_MARKER not in results[0]:
                return _reply(AIMessage(content="NEVER SAW THE ROWS"))
            # One more turn of work, which is what makes the rows a thing the
            # model has already answered on.
            return _reply(
                AIMessage(content="", tool_calls=[{"name": "ls", "args": {}, "id": "c2"}])
            )
        if len(results) == 2:
            match = re.search(r"path='([^']+)'", results[0])
            if not match:
                return _reply(AIMessage(content="NO POINTER"))
            return _reply(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "read_file",
                            "args": {"file_path": match.group(1), "limit": 5000},
                            "id": "c3",
                        }
                    ],
                )
            )
        return _reply(AIMessage(content="done"))


class _BigQueryTool:
    """A workflow tool whose result is far over the offload threshold."""

    def as_langchain_tools(self, warnings=None):  # noqa: ANN001, ANN201
        return [query_rows]


def _run(model, *, package_dir=None, data=None, with_tool=False):
    runtime = NodeRuntime(
        model=model,
        skills_package_dir=package_dir,
        skills_context=_flat_context(package_dir),
        tools={"tool.big-query": _BigQueryTool()} if with_tool else {},
    )
    agent = {
        "id": "a1",
        "type": "agent.llm",
        "data": {"tier": "deep", "summarize": False, **(data or {})},
    }
    nodes = [agent]
    plan = CompiledPlan()
    if with_tool:
        atom = {"id": "t1", "type": "tool.big-query", "data": {}}
        nodes.append(atom)
        plan.tool_bindings = {"a1": ["t1"]}
    factory = runtime.factory({"nodes": nodes, "edges": []})
    run = factory("a1", agent, plan)
    return drive_node(run, RunState(question="greet the customer"))  # type: ignore[typeddict-item]


def _flat_context(package_dir) -> str:
    if package_dir is None:
        return ""
    from openstategraph.api.capability_discovery import discover_skills

    return discover_skills(package_dir)


class TestSkillRecall:
    def test_the_body_is_absent_from_the_prompt_and_present_after_the_read(
        self, tmp_path
    ) -> None:
        model = SkillReader()
        _run(model, package_dir=_package(tmp_path))

        # Disclosure: the description is in the prompt, the body is not.
        assert "How to greet a customer properly." in model.first_system_prompt
        assert SKILL_BODY_MARKER not in model.first_system_prompt

        # Recall: the body was **actually read**, through the agent's own
        # `read_file`, at the path its own prompt advertised.
        assert any(SKILL_BODY_MARKER in r for r in model.tool_results), (
            "the skill was disclosed but its body was never retrievable"
        )

    def test_a_surface_without_file_tools_keeps_the_flat_injection(
        self, tmp_path
    ) -> None:
        """The react tier has no `read_file`, so the body must stay inline.

        Not a fallback anyone has to switch on — this is the default the
        ticket asks for, and the failure it prevents is an agent told a skill
        exists with no way to open it.
        """
        model = SkillReader()
        _run(model, package_dir=_package(tmp_path), data={"tier": "react"})
        assert SKILL_BODY_MARKER in model.first_system_prompt


class TestOffloadRecall:
    def test_a_large_result_is_retrieved_from_the_pointer_not_re_called(
        self, tmp_path
    ) -> None:
        _CALLS.clear()
        model = OffloadRetriever()
        _run(model, package_dir=_package(tmp_path), with_tool=True)

        # The rows reached the model whole, on the turn they arrived
        # (`launch-readiness/162`) — the second turn is the first one that
        # holds a tool result at all.
        assert BIG_RESULT_MARKER in model.seen[1][-1][1]

        results = model.tool_results
        assert len(results) >= 3, "the agent never followed the pointer"
        # By the last turn the rows have left the transcript...
        assert BIG_RESULT_MARKER not in results[0]
        assert "offloaded" in results[0]
        # ...and came back through the file, not through a second call.
        assert BIG_RESULT_MARKER in results[2]
        assert len(_CALLS) == 1, f"the tool was re-called: {_CALLS}"


class TestTheTokenDelta:
    """`launch-readiness/109` item 4 wants a number, not an argument.

    Measured with no model and no spend: the bytes `discover_skills`
    concatenates into every model call, against the bytes disclosure leaves in
    the prompt.
    """

    def test_disclosure_is_materially_smaller_than_flat_injection(
        self, tmp_path
    ) -> None:
        bodies = {f"skill{i}": ("body line\n" * 200) for i in range(5)}
        # Five skills, ~1,000 bytes of body each — the shape the ticket
        # measured at 10,850 bytes injected into every model call.
        pkg = _package(tmp_path, skills=bodies)
        model = SkillReader()
        _run(model, package_dir=pkg)
        disclosed = len(model.first_system_prompt)

        flat_model = SkillReader()
        _run(flat_model, package_dir=pkg, data={"tier": "react"})
        flat = len(flat_model.first_system_prompt)

        assert disclosed < flat
        # Every skill body is gone from the prompt; only names and
        # descriptions remain.
        assert flat - disclosed > 5000
