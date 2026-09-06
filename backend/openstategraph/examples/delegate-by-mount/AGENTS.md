# Delegate by Mount

Gallery example 13 of twenty — **delegation, as far as today's vocabulary
reaches**. A classifier picks one of two whole packages and that package
answers: a supervisor of *packages* rather than of agents.

| Node | One line |
| --- | --- |
| `in1` **Request** | where the request enters |
| `router1` **Which package answers this** | two exclusive branches, `database` and `web` |
| `mount-sql` **SQL QA** | gallery example 17, mounted — answers from this company's own records |
| `mount-web` **Web Research Digest** | gallery example 18, mounted — answers from the open web, and loops until it has a source it fetched |
| `out-database` / `out-web` | one output per branch |

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

## The mounts point where the catalogue always meant them to

Batch C built this example before batch D existed, so it mounted
`chained-summarizer` and `evaluator-optimizer` and recorded the substitution as
temporary. **Batch D re-pointed it** to catalogue row 13's own pair, `sql-qa`
and `web-research-digest`, once both were built, validated and smoke-run. The
smoke question travelled with the mount, exactly as batch C said it would.

Nothing was lost in the move. The property batch C chose its pair for — one
child that loops and one that does not, so the `outcome` field and its
`UNENFORCED_OUTCOME` check are exercised on the same card — holds for the new
pair too: `web-research-digest` routes a `revise` edge and can carry an
outcome; `sql-qa` is a straight line and states none, because it would have
nothing to back it.

What the new pair *adds* is that the two branches now differ in **where the
answer lives** rather than in what shape it takes. That is what delegation is
actually for: one package owns the company's records, the other owns the open
web, and the classifier's job is to know which question is which. The rules
field says so in one line — *"Route on where the answer lives, never on how the
question is phrased."*

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy delegate-by-mount
openstategraph run workflows/delegate-by-mount "How many tracks are in the database?"
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~6s — the catalogue's own
question for this row, back where it belongs:

> 3503
>
> ```sql
> SELECT COUNT(*) AS track_count FROM Track;
> ```

`decisions` is `{"router1": "b-database"}` and `outputs` holds `in1`,
`router1`, `mount-sql`, `out-database`: **the other mount never compiled a
model call**, and its package was never even loaded. The answer's shape —
a figure with the query under it — is `sql-qa`'s contract, not this document's,
which is the whole point of mounting rather than reimplementing.

## What a mount does not report

`decisions` names `router1` and stops. The mounted child ran its own tools,
and in the web branch its own grader, and none of that appears here — a mount
is one isolated step, so the parent sees the answer and not the reasoning. That
is the subagent-isolation rule holding, not a reporting gap; if you want the
child's decisions, open the child.

## Tests

`tests/` asserts the two branches reach two different packages, that each
branch has its own output, that only the looping mount claims an outcome — and
that the claim is true of the child document, not merely of its node type — and
that both mounted slugs exist on disk.
