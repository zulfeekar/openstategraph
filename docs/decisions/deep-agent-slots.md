# What a deep agent can actually offer

**Status: measured, 2026-08-22, against `deepagents 0.7.5` as installed.**
Nothing here is a design. It is the ground the configuration surface will stand
on, established so that surface offers nothing false.

Every claim below is one of two kinds, and each is labelled:

- **executed** — a script imported the installed package, built a
  `create_deep_agent`, and read what came out. Where a run was needed, a fake
  chat model supplied the turns; there is **no provider credential on this
  machine**, so nothing here is evidence about how a real model *behaves* with
  a slot, only about what the library assembles and what its tools return.
- **read** — taken from the library source or from `docs-langchain`, and said
  to be so.

The pins are `backend/tests/test_deep_agent_slot_facts.py`. A number in prose
has no way to fail, so the version, the bare stack, the full stack and the two
silent gaps are assertions rather than sentences.

## The stack, as the library actually builds it

**Executed.** With only a model, `create_deep_agent` hands `create_agent` five
middleware:

1. `FilesystemMiddleware`
2. `SubAgentMiddleware`
3. `SummarizationMiddleware` (the instance is `_DeepAgentsSummarizationMiddleware`; its `.name` is the public alias)
4. `PatchToolCallsMiddleware`
5. `AnthropicPromptCachingMiddleware`

With every optional argument supplied, eight:

`SkillsMiddleware`, `FilesystemMiddleware`, `SubAgentMiddleware`,
`SummarizationMiddleware`, `PatchToolCallsMiddleware`,
`AnthropicPromptCachingMiddleware`, `MemoryMiddleware`,
`HumanInTheLoopMiddleware` — and `_ToolExclusionMiddleware` **after all of
them** when the resolved harness profile excludes a tool.

The documented list (`/oss/python/deepagents/customization` §"Full stack") has
twelve entries. Four of the twelve are not middleware this installation can
produce: `AsyncSubAgentMiddleware` (only with `graph_id` subagents),
`BedrockPromptCachingMiddleware` and `FireworksPromptCachingMiddleware`
(`langchain_aws` and `langchain_fireworks` are **absent** — executed), and
"harness profile extras", which is a hook rather than a middleware. So
**twelve is the vocabulary; eight is the ceiling here, five is the default.**

### Where the docs and the installed code disagree

- **Excluded-tool filtering is documented at position 9** — between the harness
  profile extras and prompt caching. **Executed: it is appended last**, after
  `HumanInTheLoopMiddleware`. The code says why, and the code is right: *"Tool
  exclusion runs after custom middleware so excluded tool names are stripped
  last and cannot be restored by a custom `wrap_model_call`."*
- **"Prompt caching … Both are always registered"** (docs, bare stack item 5).
  Executed: `append_prompt_caching_middleware` appends Anthropic's
  unconditionally and the Bedrock and Fireworks ones **only if their package
  imports**. On this installation neither does. "Always registered" is true of
  one of the three.
- **`graph.py`'s own module docstring** advertises "planning, filesystem,
  subagent, and summarization middleware". **Executed: there is no planning
  middleware in `deepagents 0.7.5`** — no `TodoListMiddleware`, no
  `write_todos` tool anywhere in the package. The todo list lives in
  `langchain.agents.middleware.TodoListMiddleware` and reaches a deep agent
  only through `middleware=`. This bears directly on ticket 33, whose premise
  ("a todos slot") is a *langchain* slot, not a deepagents one.
- **`CLAUDE.md`'s cited constraint "Skills before Filesystem so skill metadata
  precedes file tools"** is the library's own words, near enough to quote:
  *"Injected **before** filesystem middleware so skill metadata is available
  before file tools run."* **"Memory after prompt caching"** likewise: *"placed
  after profile extras and the prompt caching middleware so updates to injected
  memory are less likely to invalidate the cache prefix."* Both constraints are
  the library's, not ours. That closes ticket 35's question 2.

## Slot by slot

Columns: **what it is** · **reachable today** · **what it needs** · **what a
user configures**.

### 1 · Skills — `SkillsMiddleware`

Contributes **prompt text** (a `## Skills System` section listing each skill's
name and description with a path to read for detail) and two state keys,
`skills_metadata` and `skills_load_errors`. No tools of its own — the agent
reads a `SKILL.md` with the filesystem tools. Hooks: `before_agent`,
`wrap_model_call`.

**Not reachable.** `DeepAgentNode.build_agent` passes only `model`, `tools`,
`name`, `system_prompt`, `middleware`, `subagents`; `skills=` is never passed.

**What it needs, and this is the finding of the session.** Skills are read
**through the backend**, not off the host disk. **Executed: with the default
`StateBackend`, a real skills directory on disk loads nothing and the model is
told `(No skills available)`** — no error, no warning, no `skills_load_errors`
entry. The same directory against a `FilesystemBackend(root_dir=…)` loads, and
the model sees `- **greet**: say hi to the user`. So this slot is **gated by
ticket 32** and offering it before a backend seam would ship a control that
appears to work and does nothing.

**A user would configure:** a list of source paths — and, unavoidably, the
backend those paths are relative to. It is not a boolean.

### 2 · Filesystem — `FilesystemMiddleware`

Contributes **eight tools** (`ls`, `read_file`, `write_file`, `edit_file`,
`delete`, `glob`, `grep`, `execute`) and the `files` state key. Hooks:
`wrap_model_call`, `wrap_tool_call`. It is **required scaffolding** — the
library raises rather than let a profile exclude it.

**Reachable and working today, in its default form.** Executed: a deep agent
built with no backend argument wrote `/notes.txt` and the run's final state
carried
`files: {'/notes.txt': {'content': 'hello', 'encoding': 'utf-8', …}}`.

**So "a deep agent has no workspace" (ticket 32) needs narrowing.** It has one:
`StateBackend`, in graph state, which checkpoints and survives a pause. What it
has is no *durable* workspace, no host disk, no sandbox, and — the half ticket
32 gets exactly right — **no way for a file to leave the run**, because the
streaming seam has no artifact frame.

**`execute` is the sandbox half, and it is honest about itself.** Executed
twice: with a non-sandbox backend the tool is **not bound to the model at all**
(the bound tool list is the seven file tools plus `task`), and if invoked
anyway it returns *"Error: Execution not available. This agent's backend does
not support command execution (SandboxBackendProtocol)."* `FilesystemBackend`
is also not a sandbox, so a local directory buys files, not shell.

**What it needs:** for anything beyond state — a backend. Nine are importable
here (executed): `StateBackend`, `StoreBackend`, `FilesystemBackend`,
`LocalShellBackend`, `LangSmithSandbox`, `CompositeBackend`,
`ContextHubBackend`, plus the `BaseSandbox` and `BackendProtocol` bases. The
seven third-party sandboxes ticket 32 lists are **not** all present in 0.7.5's
`backends` package; only `LangSmithSandbox` and `LocalShellBackend` are.
`StoreBackend` additionally needs a `BaseStore`.

**A user would configure:** a **choice** of backend kind, plus that kind's
argument (a root path, a store, a sandbox credential). `workflow.json` carries
the *name*, never the object — portability guardrail 3 intact.

### 3 · Subagents — `SubAgentMiddleware`

Contributes **one tool, `task`**, and a `wrap_model_call`. Present in the bare
stack because a general-purpose subagent is auto-added unless a profile
disables it — so **every deep agent already has `task`** (executed: `task` is
in the bound tool list of a bare deep agent).

**Half reachable.** `DeepAgentNode` has a `subagents` pass-through and the
compiler never fills it (`node_runtime.py` builds the tier with `name`,
`model`, `tools`, `rules`, … and no `subagents`). That is ticket 31, and this
measurement confirms its premise stands.

**What it needs:** nothing we do not have. A `SubAgent` is a dict of strings
plus tools — declarative, serialisable, exactly the shape `workflow.json`
already carries.

**A user would configure:** a list — name, description, prompt, and which of
the parent's tools it keeps. **Note for the surface:** `CLAUDE.md` says a
subagent never sees the parent's state, and that remains true of *graph state*;
`a86b4d8` measured that **run context does cross into a subagent's tools
unchanged**. Both sentences are true and the surface must not blur them.

### 4 · Summarization — `SummarizationMiddleware`

Condenses older turns. `wrap_model_call`. Present unconditionally.

**Reachable, and reachable in a way that quietly costs something.** Executed:
an instance passed through `middleware=` whose `.name` is
`"SummarizationMiddleware"` **replaces the library's tuned instance in place**
at index 2. Our compiler builds exactly such an instance whenever
`_summarizes(data)` — so on the deep tier, *turning summarization on downgrades
the library's own*. `node_runtime.py`'s comment already knows this happens; it
argues it as a reason not to fill the slot from the base, and then fills it
from the compiler for every tier including deep. Not a defect this session
fixes — recorded so the surface does not describe a checkbox as additive when
it is a replacement.

**A user configures:** a trigger and a keep window — today, effectively a
boolean plus two numbers.

### 5 · Patch tool calls — `PatchToolCallsMiddleware`

`before_agent` only. Repairs dangling tool calls when a run resumes after an
interrupt. **Always on, nothing to configure, and it should stay that way** —
this is a correctness fixture, not a capability.

### 6 · Async subagents — `AsyncSubAgentMiddleware`

Only with `graph_id` subagents, i.e. agents deployed to LangSmith. Unreachable
and out of scope; it is ticket 20's question and ticket 25's seam.

### 7 · Your middleware

Not a slot: the door the other slots are contributed through, and the door
`AbstractAgentNode.SLOT_ORDER` already uses. **Executed:** a new instance lands
after the last core entry and ahead of profile extras, prompt caching and
memory; a name collision replaces in place.

### 8 · Harness profile extras / 9 · excluded tools

Per-model presets registered with `register_harness_profile`. Reachable in
principle, and **a real lever for the Ollama-cloud posture** — a profile is
where "this model cannot hold `response_format`" would be expressed once
instead of per node. Nothing configures it today and no ticket asks for it.

### 10 · Prompt caching — `AnthropicPromptCachingMiddleware`

Unconditional, no-ops off Anthropic. **Nothing to configure, and nothing
should be** — exposing it would be exposing a provider detail as a workflow
field.

### 11 · Memory — `MemoryMiddleware`

Loads `AGENTS.md`-style files into the system prompt and the `memory_contents`
state key. `before_agent` + `wrap_model_call`.

**Not reachable** — `memory=` is never passed. **Executed:** with a
`FilesystemBackend` the file's text reaches the model. With a source the
backend cannot resolve, `download_files` returns `file_not_found` and the
middleware **`continue`s** — silence, again. So memory is **gated by ticket
32** for the same reason skills is.

**A trap worth writing down**, because it cost time here and will cost it
again: a probe middleware placed through `middleware=` sits *outside*
`MemoryMiddleware` in the `wrap_*` nesting, so it observes the system prompt
**before** memory is injected and reports memory as broken when it is not. Read
the prompt at the model, not at a middleware. That is the "first middleware
wraps all others" rule biting in the direction nobody expects.

**A user configures:** a list of source paths. Same backend problem as skills.

### 12 · Human in the loop — `HumanInTheLoopMiddleware`

`after_model`. Pauses at configured tool calls. Also generated automatically
from `permissions=`, which is the filesystem's own access control.

**Not reachable**, and it is **not free**: ticket 27 already measured that its
resume payload contradicts ours. That dependency is real and named.

**A user configures:** per-tool approval — a set of tool names, each
allow/ask.

## Order constraints, and their source

Read, from `/oss/python/deepagents/customization`:

- Skills **before** Filesystem — *"so skill metadata is available before file
  tools run."*
- Memory **after** prompt caching — *"so updates to injected memory are less
  likely to invalidate the cache prefix."*
- Patch tool calls **before** prompt caching and the tail.
- Excluded tools **last** — documented at 9, **executed as last**, and the
  source comment gives the reason: so a custom `wrap_model_call` cannot restore
  a stripped tool.

Executed corroboration of the nesting itself: a traceback through the model
node walks `FilesystemMiddleware.wrap_model_call` →
`subagents.wrap_model_call` → `summarization.wrap_model_call` →
`prompt_caching.wrap_model_call` → the model. First in the list is the
outermost wrapper, exactly as `CLAUDE.md` states.

**None of these is a position integer, and none may become one.** The surface
names a slot; the compiler owns the order.

## Recommended build order

1. **82 — a backend seam.** Depends on nothing. Everything else about
   workspace, skills and memory is downstream of it, and until it lands three
   slots can only be offered as lies.
2. **83 — skills and memory sources.** Depends on **82**. Two list fields and a
   loud failure where the library is silent.
3. **84 — subagents reach the pass-through.** Depends on nothing; the
   pass-through exists and the compiler simply never fills it. Cheapest real
   capability on the list.
4. **85 — a todo-list slot from `langchain`, not `deepagents`.** Depends on
   nothing. Corrects ticket 33's premise.
5. **86 — per-tool approval.** Depends on **27**, which must be settled first.

## What stays unpinned, and why

- **Anything about model behaviour.** No credential exists here. That a skill's
  description reaches the prompt is pinned; that a model then *reads* the
  `SKILL.md` is not, and cannot be until a provider key is available.
- **The docs' twelve-item list.** It lives on a website. The test pins what
  this installation builds, and disagreement with the site is a finding, not a
  failure.
- **The third-party sandboxes.** Named in ticket 32 from the docs; only
  `LangSmithSandbox` and `LocalShellBackend` are importable here. Pinning an
  absence would pin this laptop's install list, not a fact about the library.
