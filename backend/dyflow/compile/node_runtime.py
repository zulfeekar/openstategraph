"""Node behaviour: what each node *does* once the compiler has decided the shape.

The split with `workflow_compiler` is deliberate and load-bearing. The compiler
owns **topology** and knows nothing about models, prompts or tools; this file owns
**behaviour** and knows nothing about edges or entry points. That is what lets the
entire graph structure be tested with no API key, and it is why a new node type is
a factory entry here rather than a change to the compiler.

Routing decisions are written to `state["decisions"][node_id]`, which the
compiler's `path` function reads. So a router node *decides* and the conditional
edge *dispatches* — two responsibilities, two places, and neither has to know how
the other works.
"""

from __future__ import annotations

from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph.message import add_messages

from dyflow.abc.grader import Grader
from dyflow.abc.router import Router
from dyflow.compile.workflow_compiler import CompiledPlan


def merge_decisions(left: dict, right: dict) -> dict:
    """Reducer for the decisions channel.

    A named merge rather than last-write-wins, because two nodes can decide in the
    same superstep during a fan-out and one silently clobbering the other would be
    invisible. (CLAUDE.md: reducers are a named enum, never arbitrary functions —
    this is the `merge` member.)
    """
    return {**left, **right}


class RunState(TypedDict, total=False):
    """The shared state schema for a compiled workflow."""

    messages: Annotated[list, add_messages]
    question: str
    #: node id -> branch label chosen. Read by the compiler's `path` functions.
    decisions: Annotated[dict, merge_decisions]
    #: node id -> that node's textual output, so a downstream node can read it.
    outputs: Annotated[dict, merge_decisions]
    answer: str
    feedback: str
    attempts: int


#: Maps a tool node type to the Python tool that implements it.
#:
#: Injectable, because tool discovery is workflow-scoped (ticket 18) and the
#: shared catalogue must not accumulate every workflow's tools. Passing an empty
#: registry is valid: the agent simply gets no tools, which is a degraded run
#: rather than a crash.
ToolRegistry = dict[str, Any]


def chinook_tool_registry() -> ToolRegistry:
    """The Chinook workflow's tools, keyed by node type."""
    from tools.chinook import ExecuteSqlTool, GetTableSchemaTool, ListTablesTool

    return {
        "tool.chinook-get-schema": GetTableSchemaTool(),
        "tool.chinook-get-all-tables": ListTablesTool(),
        "tool.chinook-execute-sql": ExecuteSqlTool(),
    }


def _text(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key)
    return value if isinstance(value, str) else default


def _upstream_text(state: RunState, node_ids: list[str]) -> str:
    outputs = state.get("outputs") or {}
    return "\n".join(outputs[n] for n in node_ids if n in outputs)


class NodeRuntime:
    """Builds the callable for each node type.

    A registry keyed by node type rather than an if-chain, so adding a node type
    is a registration and `core` stays closed for modification.
    """

    def __init__(
        self,
        *,
        model: Any = None,
        tools: ToolRegistry | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.model = model
        self.tools = tools or {}
        self.max_attempts = max_attempts
        #: node id -> node type, populated by `factory()`.
        self._types: dict[str, str] = {}
        self._builders: dict[str, Callable[..., Any]] = {
            "input.text": self._input,
            "input.markdown": self._input,
            "agent.llm": self._agent,
            "route.classifier": self._router,
            "route.grader": self._grader,
            "output.formatted": self._output,
        }

    def factory(
        self, document: dict[str, Any]
    ) -> Callable[[str, dict[str, Any], CompiledPlan], Any]:
        """The `node_factory` the compiler expects.

        Takes the whole document because a node's behaviour can depend on
        *another* node: an agent needs the **type** of each tool bound to it in
        order to resolve the implementation, and the plan carries only ids.
        """
        self._types = {
            n["id"]: str(n.get("type", "")) for n in document.get("nodes", [])
        }

        def build(node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
            builder = self._builders.get(str(node.get("type", "")))
            if builder is None:
                return self._passthrough(node_id, node, plan)
            return builder(node_id, node, plan)

        return build

    # -- node kinds ------------------------------------------------------- #

    def _input(self, node_id: str, node: dict[str, Any], _plan: CompiledPlan) -> Any:
        """Seeds its configured text, or the caller's question if it has none.

        Preferring the question means a saved workflow answers *this* run rather
        than replaying whatever prompt was typed when it was saved.
        """
        configured = _text(node.get("data") or {}, "prompt") or _text(
            node.get("data") or {}, "instruction"
        )

        def run(state: RunState) -> dict[str, Any]:
            text = state.get("question") or configured
            return {"outputs": {node_id: text}}

        return run

    def _agent(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """A `create_agent` loop with the tools the canvas bound to it."""
        from langchain.agents import create_agent
        from langchain_core.messages import HumanMessage

        # Resolved by the *type* of each bound node, so wiring a tool on the
        # canvas is exactly what gives the agent that capability.
        lc_tools = []
        for tool_node_id in plan.tool_bindings.get(node_id, []):
            tool = self.tools.get(self._types.get(tool_node_id, ""))
            if tool is not None:
                lc_tools.append(tool.as_langchain_tool())

        agent = None
        if self.model is not None:
            agent = create_agent(model=self.model, tools=lc_tools, name=f"agent_{node_id}")
        #: Exposed so a test can assert the wiring produced the tools, without
        #: needing a model to prove it.
        self.last_bound_tools = [t.name for t in lc_tools]

        skills = plan.skill_bindings.get(node_id, [])
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            prompt = _upstream_text(state, upstream) or state.get("question", "")
            skill = _upstream_text(state, skills)
            feedback = state.get("feedback", "")
            if feedback:
                # The retry carries *why*, or the agent repeats itself and the
                # loop is pure cost.
                prompt = f"{prompt}\n\nYour previous answer was rejected: {feedback}"

            if agent is None:
                return {
                    "outputs": {node_id: ""},
                    "attempts": state.get("attempts", 0) + 1,
                }

            payload = [HumanMessage(content=f"{skill}\n\n{prompt}".strip())]
            result = agent.invoke({"messages": payload})
            messages = result.get("messages") or []
            text = messages[-1].content if messages else ""
            answer = text if isinstance(text, str) else str(text)
            return {
                "outputs": {node_id: answer},
                "answer": answer,
                "attempts": state.get("attempts", 0) + 1,
                "messages": messages[-1:],
            }

        return run

    def _router(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Classifies, and writes the branch for the conditional edge to read."""
        data = node.get("data") or {}
        branches = [
            line.strip() for line in _text(data, "branches").split("\n") if line.strip()
        ] or ["default"]
        router = Router(
            branches,
            fallback=_text(data, "fallback") or None,
            rules=_text(data, "rules"),
            model=self.model,
        )
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            question = _upstream_text(state, upstream) or state.get("question", "")
            decision = router.classify(question)
            return {
                "decisions": {node_id: decision.branch},
                "outputs": {node_id: question},
            }

        return run

    def _grader(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Judges, and chooses `pass` or `revise`."""
        data = node.get("data") or {}
        grader = Grader(
            criteria=_text(data, "criteria"),
            replace_defaults=_text(data, "criteriaMode") == "replace",
            model=self.model,
        )
        cap = int(data.get("maxAttempts") or self.max_attempts)
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            candidate = _upstream_text(state, upstream) or state.get("answer", "")
            verdict = grader.grade(candidate, question=state.get("question", ""))

            # Budget check before routing: a grader that keeps rejecting must
            # still let the run finish with an honest answer rather than spin.
            exhausted = state.get("attempts", 0) >= cap
            branch = "pass" if verdict.passed or exhausted else "revise"
            return {
                "decisions": {node_id: branch},
                "feedback": "" if branch == "pass" else verdict.feedback,
                "outputs": {node_id: candidate},
            }

        return run

    def _output(self, node_id: str, _node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Collects whatever reached it as the run's answer."""
        upstream = [src for src, dst in plan.edges if dst == node_id]
        conditional_upstream = [
            src for src, dests in plan.conditional.items() if node_id in dests.values()
        ]

        def run(state: RunState) -> dict[str, Any]:
            text = _upstream_text(state, upstream + conditional_upstream)
            return {"answer": text or state.get("answer", ""), "outputs": {node_id: text}}

        return run

    def _passthrough(self, node_id: str, _node: dict[str, Any], plan: CompiledPlan) -> Any:
        """An unknown node type forwards its input unchanged.

        Better than raising: a workflow containing one node this build does not
        know still runs, and the gap is visible as an unchanged value rather than
        a dead endpoint.
        """
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            return {"outputs": {node_id: _upstream_text(state, upstream)}}

        return run


__all__ = ["NodeRuntime", "RunState", "ToolRegistry", "chinook_tool_registry", "merge_decisions"]
