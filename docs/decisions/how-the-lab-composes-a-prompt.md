# How the lab composes a prompt

Read-only research into `_r&d/zee-lab` (an employer repository — nothing was
committed or altered there), to see what genuinely transfers into
`~/osg-cpl-mcp/`'s single-agent prompt.

## Where it assembles

`server/agui_app.py`, `build_system_prompt()`. Not a string constant — a
function that branches on a `deep` flag (`create_deep_agent` vs plain
`create_agent`) and interpolates today's date and the model label.

## Section order

`<narration>` → `<intro>` → `<agent_loop>` → `<tool_rules>` →
`<skill_routing>` → (deep only: `<planning>` `<coding>` `<research>`
`<subagents>`) → `<communication>` → `<output>`.

## Machinery vs per-capability

Everything in that list is machinery — fixed by the harness, identical for
every MCP server the agent is ever pointed at. The prompt is explicitly
**domain-free**: no server name, lens, table, or SQL dialect appears in it.
Domain knowledge arrives at runtime from the tools themselves — their
descriptions, and whatever a tool result's `next_step` says. There is no
developer-editable "rules" section at all in this design; the closest
analogue, skill files under `/skills/`, are still machinery-authored, just
loaded on demand instead of inlined.

Tool guidance is **not** enumerated in the prompt. `<tool_rules>` states the
discipline (read descriptions, verify before querying, read errors as ground
truth, never retry an identical call) but names no specific tool — that
comes from the tool's own description and doctrine it returns.

Missing capability handling: nothing explicit for "a tool doesn't exist" —
only "if tools cannot answer, say so plainly." No routing for a refusal vs a
genuine answer; this is the exact class of gap `launch-readiness/103`
(here) tracks for our own grader.

Offload guidance: a `CompositeBackend` splits `/skills/` (read-only,
confined to a real directory) from everything else (`StateBackend`, kept in
per-thread graph state — never touches disk, isolated per conversation
automatically). No explicit "write large results to a file" prompt
instruction; the pattern is structural, not textual.

## What was adopted into `agent1.systemPrompt`

- Explicit discover-before-query discipline: list/resolve lens → read its
  schema → only then query, never guess a column name.
- Read a tool's error, `next_step`, or empty result as the ground truth for
  what to do next, rather than blindly retrying.
- Never repeat an identical tool call; after two genuinely different
  attempts, stop and report what is missing rather than guess.

These are the "verify, don't guess" and "read errors as signal" ideas from
`<tool_rules>`, folded into the one editable rules field this package's
`agent.llm` node has. Kept short — the package's own value is staying
legible at five nodes.

## What was deliberately left out, and why

- **Mandatory two-sentence narration before/after every tool call.** Built
  for a live chat surface where the user sees nothing between a tool call
  and its result; `~/osg-cpl-mcp/` has no such streaming surface and a
  `tokenBudget: 500` agent has no room for two sentences per call on top of
  the actual work.
- **The `<output>` GeoJSON/map-rendering contract.** Zee is a vessel-map
  product; this package answers with text and findings files. Not this
  domain's shape.
- **`researcher` / `reviewer` subagents via `task`.** The zee-lab agent
  delegates open-web research and drafts to sub-agents; this package's job
  is entirely inside the MCP tool surface already, so a subagent would add
  prompt weight without a task to give it.
- **The loop-detection *middleware*.** Their version enforces the "don't
  repeat a call" rule at the harness level, inspecting actual
  `(tool, args, result)` tuples; ours is still only a prompt sentence, which
  a model can ignore. This is real and worth having, but it is
  infrastructure, not a `workflow.json` edit — filed as
  `launch-readiness/104` rather than faked as a rules-field sentence.

## Verification (untuned, verbatim)

**"which lenses are available?"** — passed. The agent called
`mcp_list_lenses` (or equivalent), returned all 15 lenses with domains, and
wrote a findings file. `grader1: pass`.

**"how many vessels departed mongstad last week?"** — the agent asked a
clarifying question about which port-role and time window "last week" and
"departed" mean, **without calling any MCP tool first** (`agent1`'s output
in the run trace shows zero tool invocations for this run). `grader1` still
returned `pass`. Tools were bound and reachable (confirmed by the first
question succeeding on the same server); this is not the unbound-tools case
`launch-readiness/103` documents. It is the same underlying gap 103 already
names — the grader has no criterion for "did the answer attempt the
question at all" — now reproduced as a clarifying question that also made
no tool call, rather than a stated refusal. Not fixed here; 103 stays open
and covers it.
