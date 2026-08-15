# Chained Summarizer

Gallery example 1 of twenty — **prompt chaining**, and the only straight line
in the set. No branch, no cycle, no tool, no mount. Four nodes:

| Node | One line |
| --- | --- |
| `in1` **Question** | where the request enters |
| `summarise1` **Summarise** | explains the subject in one short paragraph |
| `shorten1` **Cut to one sentence** | rewrites that paragraph as a single sentence |
| `out1` **Answer** | renders the sentence as Markdown |

## What it exists to exercise

One mechanism: **an agent reading another agent's `result` over its `prompt`
port**. `agent.prompt` is typed `text`; `agent.result` is typed `result`; the
edge is legal because the `text` port type *accepts* `result` as well. That
widening is what makes a chain drawable at all, and this is the smallest graph
that proves it.

The second agent is not "the same agent, asked again". It is a separate node
with its own system prompt and its own model call, and its input is the first
agent's output text — not the user's question. That is the difference between
chaining and a longer prompt.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy chained-summarizer
openstategraph run workflows/chained-summarizer \
  "Summarise what a state machine is, then cut it to one sentence."
```

Recorded 2026-08-14 on `ollama:gpt-oss:120b-cloud`, ~7s:

> A state machine is a model that defines a system's possible states and the
> rules for transitioning between them in response to inputs.

Both stages stay visible in `outputs` — `summarise1` at 532 characters,
`shorten1` at 134 — which is the assertion the example is for. Run it with
`--json` to see them.

Note what the first agent did anyway: it appended its own "One-sentence
version:" to the paragraph, unprompted. The chain still works because the
second node is the one that decides the final shape. A single prompt asking for
both would have shipped the paragraph *and* the sentence.

## The model string

`settings.model` is `ollama:gpt-oss:120b-cloud`, in **colon** form — the
workflow-level spelling. A node's own `data.model` is the frontend's **slash**
form (`ollama/gpt-oss:120b-cloud`); `NodeRuntime._resolve_model` converts it.
Two spellings, one seam, and it is easy to write the wrong one.

The catalogue asked for the bare prefix `ollama:`, on the belief that it
resolves to the cloud default. It does not — see gallery ticket 12. Every
example in this batch is pinned instead.

## Tests

`tests/` asserts the document's shape, not the model's prose: four nodes, three
edges, the `result` → `prompt` widening, and no cycle. Whether the second agent
actually shortens the first is a model question, and a stub answering it would
be theatre.
