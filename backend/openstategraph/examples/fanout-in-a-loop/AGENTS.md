# Fanout In A Loop

Gallery example 9 of twenty — the only cycle in the gallery that **contains a
`Send`**, and the example where "a lap is not a superstep" stops being a
slogan.

| Node | One line |
| --- | --- |
| `in1` **Brief** | where the numbered brief enters |
| `lead1` **Planner** | splits the brief into subtasks and fans them out |
| `worker1` **Analyst** | runs once per subtask, in parallel |
| `join1` **Join** | joins the worker results into one Markdown report |
| `grader1` **Report review** | passes the report, or sends the plan back |
| `out1` **Report** | renders whatever passed |

```
in1 ─▶ lead1 ═Send═▶ worker1 ─▶ join1 ─▶ grader1 ──pass──▶ out1
        ▲                                   │
        └────────────── feedback ───────────┘ revise
```

`orchestrate.supervisor` is one of only two nodes with a `feedback` input; this
is the example that uses it.

## One lap costs four supersteps

Measured, not asserted. The recorded run below did **two** laps and the
checkpointer logged **14** supersteps: planner, fan-out, join, grader — four per
lap — plus the entry and exit steps. Three laps would be eighteen.

That ratio is why `recursion_limit` must never be labelled "max iterations" in
any surface. It defaults to 50 here, which this run used 28% of while looping
twice.

## Write each numbered item so it stands alone

`Orchestrator.split` is three regexes tried in order — a numbered list, then
semicolons, then the literal word "and" — and a `Send` payload carries **only**
the subtask text. A worker never sees the brief, the other subtasks, or the
conversation. Two consequences this package is shaped around:

- **No preamble before the list.** A first line of prose above `1.` becomes
  subtask #1 in its own right, and with `maxSubtasks` set to the number of list
  items the *last* real item is then silently truncated away. A control run did
  exactly this: the preamble became `task-1-1` and item 3 never ran.
- **No cross-references between items.** "Judge which of those two is safer"
  reaches a worker that has never seen the two, and comes back as *"I cannot
  provide a safety judgment because the specific two options you want compared
  were not included in your request."* — verbatim, from a control run. Item 3
  below names both approaches instead.

Both belong to gallery ticket 15.

## The feedback edge re-plans, and this is where that was fixed

It used not to. `Orchestrator.split` was deterministic on an instruction that
did not change between laps, so a rejected report was re-planned into **exactly
the same subtasks** with the grader's feedback appended to each one's text: the
workers got another go and the division of labour could not change, however
precisely the grader named what was wrong with it. Gallery ticket 23.

Fixed by gallery ticket 15's planning call plus one change of order — the
rejection is passed *into* `split(instruction, feedback)` rather than folded in
after it. This document's supervisor carries rules, so its plan is a model call
and the rejection reaches it. Live, 2026-08-15, three laps: lap 3's third
subtask read

> Judge which deployment approach is safer to operate, **beginning the response
> with a sentence that names the chosen approach**, then explain the reasons …

— the grader's structural complaint, folded into the *plan* rather than
appended to it. A supervisor with no rules keeps the old behaviour exactly: the
deterministic splitter ignores the feedback argument, by design and documented,
because a regex handed a critique turns it into more work to split.

`maxAttempts: 3` — and the supervisor is the only node here that increments
`attempts`, so on this graph one lap does cost one attempt.

## The worker's `role` is read by the worker

It used to reach the supervisor's archetype-labelling call and nothing else, so
"six lines at most" on the card shortened nothing and the recorded run's
sections were far longer. With one worker wired, labelling short-circuits, so
the field was inert entirely. Gallery ticket 16, fixed: `role` is context in
the worker's own prompt now. Live, 2026-08-15, same card text — the three
sections came back at **6, 6 and 4 lines**, each naming a failure mode, who is
on the hook and what recovery costs. The card text was written as a statement
of intent and is now a statement of behaviour.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy fanout-in-a-loop
openstategraph run workflows/fanout-in-a-loop "$(cat <<'EOF'
1. Describe deploying a Python service in a Docker container on a virtual machine you run yourself.
2. Describe deploying the same Python service to a managed platform that runs the container for you.
3. Judge whether a self-run Docker virtual machine or a managed container platform is safer to operate, and name the one you picked in your first sentence.
EOF
)"
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~55s, `attempts: 2` — one
replan, then a genuine pass (`2 >= 3` is false, so the budget was not the
reason it stopped). `# Deployment comparison` with three `###` sections in
task-id order, `task-1-1` … `task-1-3`, the last opening:

> Managed container platform is safer to operate.

`decisions` is `{"grader1": "pass"}`. The generation prefix in the ids
(`task-1-*`) is how you can tell a replan happened at all: ids are minted
`task-{generation}-{n}` precisely so a second plan cannot alias the first one's
results in the shared `worker_results` map.
