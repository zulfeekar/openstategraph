# {{name}}

An OpenStateGraph workflow package, scaffolded from the **loop** template — an
answer that gets reviewed, and rewritten until it is good enough.

## What is in here

```
                      ┌──────── revise ────────┐
                      ▼                        │
input.text → agent1 (Draft) ────→ grader1 (Review) ──pass──→ output.formatted
```

Three ideas, one document:

- **`agent1`** — writes the answer. Its **rules** are the only editable part of
  its prompt; the preamble and the output contract are locked. Note what the
  rules say about feedback: when a previous attempt comes back, the feedback
  *is* the specification — fix what it names, keep what it did not object to.
- **`grader1` (`route.grader`)** — judges that answer against your criteria and
  routes on the verdict. `pass` goes to the output; `revise` goes **back** to
  the agent's `feedback` port.
- **The edge from `revise` to `feedback`** — this is the whole template. It is
  legal to draw only because `feedback` is a typed feedback input, which is
  also why you cannot create a loop by accident: the type system is the gate.

## The words for this

A **revision loop**: run a step, judge it, run it again with the objection
included. It is a cycle *in* the graph, not a wrapper around one — which is why
adding one is two edges rather than a different tool.

`maxAttempts` on the grader bounds it, and it counts **attempts**. A loop that
never satisfies its criteria gives up and emits its best answer rather than
running forever. That is a different number from the run's **step budget**
(`recursion_limit`), which counts *supersteps* across the whole graph. Set that
one in the document — `"settings": {"recursionLimit": 200}` — and every run of
this package gets it. Size it in supersteps, never in laps: a lap that fans out
spends one per branch.

Discovered by convention: `tools/`, `functions/`, `middlewares/`, `skills/`,
`tests/`, `data/`.

## Run it

```bash
openstategraph validate .          # compile-check without spending a token
openstategraph run . "your request here"
openstategraph graph .             # the compiled topology, as Mermaid text
```

A run costs two model calls when the first draft passes — agent, grader — plus
two more for every revision. A loop is not free, which is the argument for
criteria that are specific enough to be satisfied.

## The obvious next step

1. **Make the criteria yours.** `grader1`'s criteria are the contract for what
   "good" means here, and a vague one loops until it runs out of attempts. They
   *extend* the built-in criteria; switch to `replace` only when you mean it.
2. **Say what is wrong, not that it is wrong.** The last criterion asks the
   grader to be specific enough that the next attempt can act. Delete it and
   the loop still runs — it just stops improving anything.
3. **Wire a tool.** Drop a `BaseTool` subclass into `tools/` and connect its
   `tool` port to `agent1`'s `tools` bus. An agent that cannot look anything up
   will be graded on what it can invent.
4. **Reuse it, rather than redrawing it.** This whole package can become a
   single node in another workflow — mount it, and the loop runs isolated, task
   in and answer out. Change it here and every workflow that mounts it changes;
   that is the difference between mounting a package and starting from a
   template, which severs the link at creation.
5. **Publish it.** This package is a **draft** (`"published": false`). Publish
   from the editor's Workflows panel, or
   `POST /api/workflows/{{slug}}/publish`, to put it on the customer `/chat`
   surface.
