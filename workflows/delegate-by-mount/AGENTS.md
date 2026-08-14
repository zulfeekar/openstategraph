# Delegate by Mount

Gallery example 13 of twenty — **delegation, as far as today's vocabulary
reaches**. A classifier picks one of two whole packages and that package
answers: a supervisor of *packages* rather than of agents.

| Node | One line |
| --- | --- |
| `in1` **Request** | where the request enters |
| `router1` **Which package answers this** | two exclusive branches, `explain` and `release_note` |
| `mount-explain` **Chained Summarizer** | gallery example 1, mounted |
| `mount-note` **Evaluator / Optimizer** | gallery example 4, mounted — it loops until its own grader passes |
| `out-explain` / `out-note` | one output per branch |

Each branch gets its **own** `output.formatted`. Two edges into one output
node load and compile, but the capacity rule makes drawing the second edge
*replace* the first, so a converging branch is not redrawable — gallery
ticket 13, and every example in the twenty avoids it the same way.

## Why this is a substitute, and for what

The catalogue's candidate was **subagent-as-tool**, and it cannot be drawn.
`workflow.subgraph` has exactly two ports, `input` and `result`, and nothing
in the catalogue emits a `tool` type except tool atoms — so a mounted package
can never reach an agent's `tools` bus. Delegation today is call *and return*
through a graph step, which is what this document draws. The gap is
organisms-first-class ticket 31.

## Deviation from the catalogue, deliberate

Catalogue row 13 mounts `sql-qa` and `web-research-digest` — examples 17 and
18, which **batch D has not built yet**. Rather than defer this example out of
its own batch, it mounts two packages that exist today. The mechanism under
test is heterogeneous mounts as exclusive branches, which is package-agnostic,
and re-pointing a mount is a one-field edit (`data.workflow`) if batch D wants
the original pairing back.

The pair chosen is not arbitrary. The two packages differ in the way that
matters to a mount card: `chained-summarizer` is a straight line, and
`evaluator-optimizer` closes a loop. So `mount-note` can carry an `outcome`
— *"Loops until its own grader passes the note."* — and mean it. That claim is
checked at compile time: a mount that states an outcome its child cannot
enforce is a warning (`Finding.UNENFORCED_OUTCOME`), keyed on the child
actually routing a `revise` edge rather than on the node type. `mount-explain`
states no outcome, because it would have nothing to back it.

## Smoke run

```
openstategraph run workflows/delegate-by-mount \
  "Write the release note for a fix to a crash when the export button was pressed twice."
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~12s:

> The app crashed when the export button was pressed twice. After the fix, it
> completed the export without crashing when the button was pressed twice.

Two sentences, defect then fixed behaviour, no marketing language — which is
`evaluator-optimizer`'s contract, not this document's. `decisions` is
`{"router1": "b-release-note"}` and `outputs` holds `in1`, `router1`,
`mount-note`, `out-note`: **the other mount never compiled a model call**, and
its package was never even loaded.

The catalogue's own question for this row ("How many tracks are in the
database?") belongs to `sql-qa` and moves with the mount if it is ever
re-pointed.

## What a mount does not report

`decisions` names `router1` and stops. The mounted child ran its own grader
and reached its own verdict, and neither appears here — a mount is one
isolated step, so the parent sees the answer and not the reasoning. That is
the subagent-isolation rule holding, not a reporting gap; if you want the
child's decisions, open the child.

## Tests

`tests/` asserts the two branches reach two different packages, that each
branch has its own output, that only the looping mount claims an outcome, and
that both mounted slugs exist on disk.
