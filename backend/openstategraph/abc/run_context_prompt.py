"""The run-context block, delivered per **invocation** instead of per build.

`launch-readiness/182`. `organisms-first-class/72` made a prompted agent tell
its model what the run was started with — which tenant, which case id — by
rendering a **Context** section and passing it to the node's constructor. That
put a per-run value inside something built once and kept: the compiler's agent
memo, whose own comment says *"one compiled graph serves many runs, and this
cache outlives all of them"*. Keyed on the rendered block, a workflow declaring
a `caseId` built one fully-assembled agent per run and evicted none.

So the key was never the problem worth fixing — the **lifetime of the value in
it** was. This module is the seam that takes it back out:

- the compiler renders a fixed `MARKER` into the agent's context layer, once,
  at the position the section has always occupied — above the developer's rules
  and below the preamble, with the locked output contract still last;
- the node writes this run's rendered section onto the **invocation**, as
  ``run_context_section``;
- `RunContextMiddleware` substitutes one for the other at the moment the model
  is called.

This is the shape deepagents' own `RubricMiddleware` already uses one layer
down — *"the rubric text rides on invocation state, so one middleware serves
every question"* — applied to the other generated block that varies per run.

**It strengthens `72` rather than trading against it.** A cache key is a
promise that two different values land in two different entries; this keeps no
per-caller entry at all. The section is rendered inside the node body, from the
values ambient to *that* run, and travels only in that invocation's state. Two
callers cannot collide because there is nothing shared to collide in.

**Why a marker and not an appended block.** Prompt order is the substance
(`CLAUDE.md`, "the output contract goes last"): a middleware that appended the
section to the system prompt would put generated context *after* the contract
it must never countermand. Substituting in place is the only delivery that
preserves the composition `SystemPrompt` already decided.

**Why the marker is absent when nothing is declared.** A workflow that declares
no prompt-context field gets no marker, no slot and no middleware, so its
system prompt is byte-for-byte what it was. A feature nobody uses pays nothing,
which is the rule `compile/run_context.py` opened with.
"""

from __future__ import annotations

import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest
from langchain_core.messages import SystemMessage
from typing_extensions import NotRequired

#: The slot this middleware fills. Declared in `AbstractAgentNode.SLOT_ORDER`,
#: which owns the order; naming it here would be the second spelling.
RUN_CONTEXT_SLOT = "run-context"

#: What the compiler renders where the section goes. Deliberately not a
#: `{{key}}` placeholder: `render_run_context` substitutes that grammar in
#: *author* text, and a marker sharing it would be two mechanisms answering to
#: one pattern. Deliberately conspicuous, too — if this ever survives into a
#: prompt, the thing a reader sees should name the seam that failed.
MARKER = "[[openstategraph:run-context]]"

#: The marker plus whatever blank space glued it to its neighbours. The section
#: is one part of a `"\n\n".join`, so removing it must remove the join as well
#: or an empty run leaves a hole where a paragraph break used to be.
_MARKER_WITH_SPACE = re.compile(r"\n*" + re.escape(MARKER) + r"\n*")


def resolve_marker(prompt: str, section: str) -> str:
    """`prompt` with the marker replaced by `section`, or closed up if empty.

    A run that supplies nothing for every opted-in field renders `""` — which
    `run_context_prompt_section` documents as its answer for "what is not known
    is not written down" — and the correct prompt then is the one the workflow
    would have had with the feature switched off, not one carrying an empty
    heading or a leftover marker.
    """
    if MARKER not in prompt:
        return prompt
    if not section:
        return _MARKER_WITH_SPACE.sub("\n\n", prompt).strip()
    return prompt.replace(MARKER, section)


class RunContextPromptState(AgentState):
    """The one key this middleware adds to the agent's state.

    `NotRequired`, because every existing invocation omits it and an agent
    whose workflow declares no run context never writes it.
    """

    run_context_section: NotRequired[str]


class RunContextMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Substitutes this invocation's run-context section into the prompt.

    It wraps the *model* call rather than hooking `before_model`, because what
    it changes is the request — and `ModelRequest.override` is the library's
    own way to say so without mutating a shared object. Both spellings are
    implemented: the agent node family is `async def` since `async-first/06`,
    and a middleware that only implemented the sync hook would silently do
    nothing on the path every run actually takes.
    """

    name = "RunContextMiddleware"
    state_schema = RunContextPromptState

    def _resolved(self, request: ModelRequest) -> ModelRequest:
        prompt = request.system_prompt
        if not prompt or MARKER not in prompt:
            return request
        section = str(request.state.get("run_context_section") or "").strip()
        return request.override(
            system_message=SystemMessage(content=resolve_marker(prompt, section))
        )

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        return handler(self._resolved(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        return await handler(self._resolved(request))


def build_run_context_middleware() -> RunContextMiddleware:
    """A function rather than a bare class reference, matching `narration`.

    The compiler names a slot and asks for an instance; what that instance is
    assembled from stays here, so a later argument (a per-workflow spelling of
    the section, say) does not become a change at every call site.
    """
    return RunContextMiddleware()
