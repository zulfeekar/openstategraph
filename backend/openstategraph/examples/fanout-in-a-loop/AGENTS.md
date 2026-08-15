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

## The feedback edge re-dispatches; it does not re-plan

`Orchestrator.split` is deterministic on the instruction, and the instruction
does not change between laps. So a rejected report is re-planned into **exactly
the same subtasks**, with the grader's feedback appended to each one's text.
The workers get another go; the division of labour cannot change, however
precisely the grader names what is wrong with it. Gallery ticket 23.

`maxAttempts: 3` — and the supervisor is the only node here that increments
`attempts`, so on this graph one lap does cost one attempt.

## The worker's `role` is not read by the worker

It reaches the supervisor's archetype-labelling call and nothing else, so
"six lines at most" on the card does not shorten anything — the recorded run's
sections are far longer. With one worker wired, labelling short-circuits and
the field is inert entirely. Gallery ticket 16; the card text is kept as the
statement of intent it will become once that lands.

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
