# Stranger install, run two — 0.3.0rc3

Second stranger run (`launch-readiness/23`), against the fixed artifact. Run one
(`stranger-install-2026-08-23.md`) never reached an answer. This run's job was to reach
one and time it.

Isolation: `/tmp/stranger2`, own venv, `.env` copied from the owner's checkout. Server run
from `/tmp/stranger2`, never from the checkout.

Concept stated to the product, in the owner's words, naming no node type or port:

> "I want something that answers questions about the LangChain Python API using the
> official documentation, and if an answer is vague or not actually supported by the docs,
> it should try again rather than publishing it."

## T0

`2026-08-24T05:56:39Z` — `pip install` began.

## 1. Install — 28s, clean

```
pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ "openstategraph[server,anthropic]==0.3.0rc3"
```

`25.768s total`, 49 packages, no build step, no compiler, no warning except pip's own
version notice. **No surprises.** langchain 1.3.16 / langgraph 1.2.11 resolved from real
PyPI while openstategraph came from TestPyPI — the two-index invocation worked first time.

## 2. `providers` — the best output in the product

```
default:     anthropic:claude-haiku-4-5 — the only provider integration installed, and
             it has a credential
anthropic    configured   anthropic:claude-haiku-4-5   (default)
             reads ANTHROPIC_API_KEY; it is set (sk****)
```

and then, unprompted:

> No provider was called. "configured" means a credential is present in this environment —
> not that the endpoint is reachable, and not that a request will be answered.

It also volunteered that `.env` is read by the CLI and **not** by a server started any
other way. Both are exactly the things a stranger gets wrong. Nothing to fix here.

## 3. `serve` — clean

```
editor  http://127.0.0.1:8123/
chat    http://127.0.0.1:8123/chat
api     http://127.0.0.1:8123/api/health
INFO ... authentication: off — every caller that can reach this port has full access.
```

Auth warning is present and names the fix. Good.

## 4. `/chat` is the wrong door for a new user

`/chat` renders "No workflows are published yet — open the editor, open its Workflows
panel, and press Publish on one." Correct and actionable, but it means the chat surface —
the thing the brief calls the obvious first stop — cannot be a stranger's entry point.

## 5. STUCK — no visible way to ask the product to build something

In the editor at 1600x1000 (at 800px the palette, canvas and inspector overlap into
illegibility — separate finding), I read the whole toolbar. Twenty controls. None of them
says *describe what you want and I will build it*. The closest label is **"Ask the
workflow"**, so as a stranger that is what I clicked.

**It did nothing.** No panel, no toast, no disabled state, no explanation. Console shows
only an unrelated 404 (favicon); no request was made. A stranger's single most likely
first click is a silent no-op.

Tried, in order: read every toolbar label; clicked "Ask the workflow"; checked the console
and the network log for a swallowed error; looked for an architect/assistant affordance in
the palette. Then stopped and consulted the docs.

### (a) The answer

**There is no in-app "describe what you want" surface in a wheel install, by design.**
The build-me-a-workflow flow is a workflow named `workflow-architect`, and it lives in the
*repository's* `workflows/`, outside `backend/` — so it is not packaged. For a wheel
install the documented substitutes are `openstategraph mcp` (your own MCP client's model
becomes the composer) or `openstategraph new <slug> --template minimal|routed-qa|team`.

Per the brief, *"this platform cannot do that yet"* is a **correct** outcome, and this is
one: the interview I was sent to be interviewed by does not exist in the artifact under
test. **Everything below is therefore a template-scaffold run, not an interview run.**

### (b) Where it was hiding

`README.md` line 263, inside a parenthetical about a *deleted example's* recorded cost —
under no heading a stranger would search, and reached only because I grepped for
"architect". The editor itself says nothing. Nothing in `docs/getting-started.md` came up.
The one place a stranger looks — the editor toolbar — offers "Ask the workflow", which is
a different feature and which silently does nothing.

## 6. The path a wheel install actually has: `openstategraph new --template`

`new --list-templates` is genuinely good, and it **offered existing capability rather than
proposing to build new**:

```
minimal    input to agent to output — the smallest thing that runs (one model call).
loop       an agent drafts, a grader reviews, weak answers go back — a revision loop.
routed-qa  a router picks a branch, an agent answers, a grader sends weak answers back.
team       supervisor plus worker plus grader — mountable as a Team node elsewhere.
```

`loop` is the concept's second half exactly. Scaffolded it, and the default grader criteria
already read "Every factual claim must come from a tool result or be marked as uncertain —
never invented." Nothing about the shape had to be invented by me.

**What the template does not supply is the concept's first half — the documentation.**
`knowledge build` does not help: it generates prose from *wiring* it recognises (SQL,
mounts, platform tools), so there is no "ingest the official docs" path. But
`tool.web-search` (keyless, DuckDuckGo) and `tool.web-fetch` **do** ship, so the concept is
supportable. I added both to the agent's `tools` bus and pointed the two prompts at
`python.langchain.com`. `validate` then reported:

```
VALID
Topology: 4 graph nodes · entry ['in1'] · exits ['out1']
Routes: {'grader1': ['pass', 'revise']}
Tool bindings: {'agent1': ['search1', 'fetch1']}
```

### `validate <slug>` and `new <slug>` disagree about where packages live

`new langchain-docs-qa` wrote to `workflows/langchain-docs-qa`. `validate langchain-docs-qa`
then said *"no workflow document at /private/tmp/stranger2/langchain-docs-qa/workflow.json"*
— it resolved against cwd, not the workflows root, because `init .` had refused (the
directory already held 4 files) so there was no project marker. The error names a path but
never says *"this directory is not an OpenStateGraph project; run `init`"*, which is the
actual cause. `validate workflows/<slug>` works.

## 7. THE HEADLINE — 6 minutes 54 seconds

- `pip install` began `2026-08-24T05:56:39Z`
- first correct, documentation-grounded answer `2026-08-24T06:03:33Z`

**T = 6m54s from `pip install` to first useful answer**, including reading the README to
discover the architect does not ship. Run one never got here.

## 8. The answers — verified against the docs, not scored on plausibility

Verified independently through the `docs-langchain` MCP server.

**Q1.** *"what is the function that creates a ReAct-style tool-calling agent, and what are
the names of its parameters for the model and for the tools?"* — 70s, 3 attempts.

> **Function:** `create_agent` (from `langchain.agents`) … **For the model:** `model` …
> **For the tools:** `tools`

**CORRECT.** Confirmed: `from langchain.agents import create_agent`,
`create_agent(model=..., tools=...)`. It also volunteered, correctly, that
`create_react_agent` is the superseded v0 name.

**Q2.** *"create_agent renamed one parameter that create_react_agent used to call 'prompt'.
What is its new name?"* — 23s, passed the grader first attempt, no warning.

> "The prompt parameter has been renamed to system_prompt"

**CORRECT**, and it quoted the migration guide accurately with the right URL.

**Q3 — the break test.** *"what does the 'temperature_decay' parameter of create_agent do,
and what is its default value?"* — 22s. There is no such parameter.

> "I cannot find a `temperature_decay` parameter for the `create_agent` function in
> LangChain 1.x."

**HONEST REFUSAL — PASS.** It listed the real parameters, declined to invent a default, and
asked where I had seen the name. It did not hedge and it did not confabulate. This is the
single best behaviour in the run.

## 9. THE WORST FINDING — the loop's promise inverts under load

The concept asked for a thing that "should try again rather than publishing it". What it
does when trying again runs out is **publish the rejected answer**, and who is told depends
on an audience flag.

The CLI is honest:

> warning: Grader "grader1" ran out of attempts and published an answer it had rejected.
> Its last reason: The answer claims to cite official documentation but provides a URL …
> that was not actually fetched and verified by the agent.

The HTTP API, at the **default** `audience: "customer"`, is not. Same document, same
question, `POST /api/runs`:

```
keys:     ['answer','attempts','decisions','developer','mermaid','outputs','thread_id']
attempts: 3
developer: None
```

`attempts: 3` — it exhausted the loop — and `developer: None`. `warnings` is a field of
`DeveloperChannelResponse` **only**; a customer-audience `RunResponse` has no field that
could carry it. So the customer receives a grader-rejected answer, unlabelled,
indistinguishable from one that passed. `/chat` is a customer-audience surface.

**And on that run the published answer was wrong:**

> "Based on the LangChain 1.x reference, the function is **`create_react_agent`**, not
> `create_agent`. Here is the corrected answer:"

That is backwards — and it is the same workflow and the same question that answered
correctly through the CLI seven minutes earlier. So: a wrong answer, produced after three
rejections, delivered to the customer channel with nothing to indicate any of that.

Note also the leaked scratchpad. The customer answer opens *"Perfect. I now have the
official documentation."* — the agent's inner monologue is published verbatim.

### Why the grader could never be satisfied

Its rejection reason is *"provides a URL that was not actually fetched and verified by the
agent"*. The grader receives the candidate **text**; it cannot see the agent's tool calls.
So a criterion of the form "traceable to a page the agent actually fetched" is
unsatisfiable in principle — the grader has no access to the fact it is asked to check. It
rejected a *correct* answer three times on those grounds. The template's own default
criteria ship with this shape ("must come from a tool result"), so this is not something I
invented by writing bad criteria.

## 10. Editor observations

- **At 800px wide the editor is unusable** — palette, canvas and inspector overlap into
  illegible layers. 1600px is fine. No responsive floor, no minimum-width notice.
- **"Ask the workflow" is a silent no-op** with nothing published. No toast, no disabled
  state, no request.
- **"Arrange automatically" overlaps tool cards with the agent they bind to** — Web Search
  and Web Fetch landed on top of the Draft agent's card.
- **Fit-to-screen left the graph off-canvas** after auto-arrange: 71% zoom, minimap showing
  nodes, canvas viewport empty.
- **The model picker offers models whose extra is not installed.** `Claude`, `gpt-4.1`,
  `gpt-4o`, `gpt-oss:120b-cloud` are all listed, unmarked, though `openstategraph providers`
  correctly says openai and ollama each "needs its extra". The CLI knows; the picker does not
  say. Choosing one is a trap the picker set.
- **Genuinely good:** the Diagnostics panel volunteered "Text Input has no prompt, so this
  workflow takes its question at run time", and the Packages palette refused to let the
  package mount itself — *"Would mount itself here — a mount cycle can never terminate."*

## 11. Scoring

| | |
| --- | --- |
| Install | clean, 28s, no surprises |
| `providers` | best surface in the product |
| Interview | **does not exist in a wheel install** — correct outcome, badly signposted |
| Existing vs new | **offered existing** (`--template loop`) — the right instinct |
| Answers | 2 of 2 verifiable questions correct via CLI; 1 of 1 wrong via HTTP |
| Honest refusal | **PASS** — clean, specific, no confabulation |
| Silent failures | 3 — customer-channel warning loss, "Ask the workflow", the model picker |
| Time to first useful answer | **6m54s** |

Provider ladder: **Claude only.** `anthropic:claude-haiku-4-5` was the default and worked for
every call. No fallback to OpenAI or Ollama was needed, so neither was exercised.
