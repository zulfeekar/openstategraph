# Classifier Router QA

Gallery example 3 of twenty — **routing**, and the only pure one: three
mutually exclusive terminal branches, no grader, no loop, no tool.

| Node | One line |
| --- | --- |
| `in1` **Question** | where the question enters |
| `router1` **Intent** | one model call sorts the question into one of three branches |
| `agent-world` **World Facts** | facts about the world; says what it cannot know rather than guessing |
| `agent-howto` **How To** | a short numbered procedure |
| `agent-general` **General** | everything else, briefly |
| `out-world` / `out-howto` / `out-general` | one output per branch |

One router call plus exactly one agent call per run. The other two agents never
execute — not "execute and get discarded".

## Three branches, three outputs — deliberately

The shipped `routed-qa` template converges two branches onto a single
`output.formatted.result`. That document loads and compiles, but `result` is a
`maxConnections: 1` input, and the capacity rule resolves a second edge by
**replacing** the first. So the template ships a graph nobody can redraw: open
it, nudge the second link, and the first one is gone.

Every gallery example therefore gives each exclusive branch its own output.
It costs one card per branch and it is the only shape that survives being
edited. Gallery ticket 13 carries the inconsistency.

## Branch ids are the wire; branch names are the vocabulary

A router's outputs are **dynamic ports** named `branch:<id>`, so the edge is
bound to the branch's stable `id` (`b-world`), not to its display `name`
(`world_facts`). Rename a branch and the wiring survives; delete one and its
edge has nowhere to land. `fallback` names a branch by `name`, and must name a
branch that exists.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy classifier-router-qa
openstategraph run workflows/classifier-router-qa "What time is it in Tokyo?"
```

Recorded 2026-08-14 on `ollama:gpt-oss:120b-cloud`, ~7s:

> I'm not able to determine the current time in Tokyo right now because I don't
> have access to live time-keeping data. If you can provide the present UTC
> time, I can calculate the corresponding time in Tokyo (UTC + 9 hours).

Matches the expected shape exactly. `decisions` is `{"router1": "b-world"}` —
one branch named, by id — and `outputs` carries `in1`, `router1`,
`agent-world`, `out-world` and nothing else: the other two agents left no
trace because they never ran.

The refusal is the World Facts prompt doing its job. A model with no clock that
answers "it is 3:47 PM" is the failure mode this branch is written against.
