# {{name}}

An OpenStateGraph workflow package, scaffolded from the **routed-qa** template
— the shape most real assistants end up with, and the one that teaches the
vocabulary.

## What is in here

```
                        ┌── question ──→ agent1 (Answerer) ──→ grader1 ──pass──┐
input.text → router1 ───┤                        ▲                 │          ├→ output.formatted
                        └── smalltalk ─→ agent2 (Greeter) ─────────┼──────────┘
                                                 └──── revise ─────┘
```

Four ideas, one document:

- **`router1` (`route.classifier`)** — classifies the incoming text into one
  named branch and nothing else. Branches are ports, so each one is wired to a
  different destination. Its **rules** are the only editable part of its
  prompt; the preamble and the output contract are locked, because a router
  whose answer cannot be parsed is a broken router.
- **`agent1`** — the specialist that actually answers. Only this branch pays
  for the grader.
- **`grader1` (`route.grader`)** — judges the answer against your criteria.
  `pass` goes to the output; `revise` goes **back** to the agent's `feedback`
  port. That is the evaluator-optimizer loop, and it is legal to draw only
  because `feedback` is a typed feedback input.
- **`agent2`** — the cheap path. Not everything deserves three model calls.

`maxAttempts` on the grader bounds the loop. It is attempts, not supersteps —
a loop that never satisfies its criteria gives up and emits its best answer
rather than running forever.

Discovered by convention: `tools/`, `functions/`, `middlewares/`, `skills/`,
`tests/`, `data/`.

## Run it

```bash
openstategraph validate .          # compile-check without spending a token
openstategraph run . "your question here"
openstategraph graph .             # the compiled topology, as Mermaid text
```

A run costs up to three model calls: router, agent, grader — plus one more per
revision.

## The obvious next step

1. **Make the criteria yours.** `grader1`'s criteria are the contract for what
   "good" means here. They *extend* the built-in ones; switch to `replace` only
   when you mean it.
2. **Add a branch.** A router with two branches is a starting point, not a
   design. Add one per kind of request you actually get, and give each its own
   destination — an agent, a `workflow.subgraph`, or a Team.
3. **Wire a tool.** Drop a `BaseTool` subclass into `tools/` and connect its
   `tool` port to `agent1`'s `tools` bus. An agent that cannot look anything up
   will be graded on what it can invent.
4. **Publish it.** This package is a **draft** (`"published": false`). Publish
   from the editor's Workflows panel, or
   `POST /api/workflows/{{slug}}/publish`, to put it on the customer `/chat`
   surface.
