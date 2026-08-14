# Morning Brief

Gallery example 20 of twenty — **many sources, one report**, and the only
fan-out whose workers carry tools. Three workers run in parallel, each holding
a **different** one: the open web, this team's handbook, and the platform's own
list of workflows.

| Node | One line |
| --- | --- |
| `in1` **Brief request** | a numbered list, one line per source |
| `lead1` **Editor** | splits the list and labels each item with the worker that owns it |
| `skill1` **How a brief is sourced** | one rules layer, read by all three workers |
| `t-search` → `worker-web` **Web researcher** | `tool.web-search` |
| `t-knowledge` → `worker-handbook` **Handbook reader** | `tool.knowledge-lookup` over this package's `knowledge/` |
| `t-platform` → `worker-platform` **Platform inspector** | `tool.platform-list-workflows` |
| `join1` **Assemble** | one `###` section per subtask id |
| `out1` **Brief** | the report |

Distinct from example 5, whose archetypes differ by *role* rather than by
capability, and from example 18, which is one agent looping over tools rather
than several each owning one.

## The question is a bare numbered list, and that is load-bearing

`Orchestrator.split` tries `_NUMBERED = (?:^|\n)\s*\d+[.)]\s*` first. A summary
line above the list becomes **subtask #1**, and with `maxSubtasks: 3` the third
real item is then dropped without a word — gallery ticket 15's second facet,
found by a batch B control run. So the smoke question is three numbered lines
and nothing else. `tests/` pins both halves: the split this question produces,
and the one the preamble version would have.

## A worker cannot be told how to answer, so the skill does it

`orchestrate.worker` declares no prompt field, and `role` is read by the
*supervisor's* labelling call, not by the worker (gallery ticket 16). A
`systemPrompt` typed onto a worker card would be silently inert. The only lever
is the `skill` port — so one `input.skill` fans out to all three workers, since
`input.skill.skill` is `maxConnections: null` and each worker's `skill` input
takes one.

Its central sentence earned its place on the very first run:

> **A tool that refuses is not a tool that found nothing.**

## Smoke run

```
openstategraph run workflows/morning-brief "1. What changed in the most recent Python release?
2. What does our release checklist require before a tag?
3. Which workflows exist on this platform?"
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`. `lead1` reported *"Planned
3 subtask(s)"*; the report came back as `# Morning brief` with three task-id
sections, each from its own worker:

> **task-1** — The web search for "latest Python release notes 2026" could not
> be completed because the search tool returned a rate-limit/challenge error,
> so no release information could be retrieved.
>
> **task-2** — Our release checklist requires seven items before a tag can be
> cut: … and the previous release must have been live for at least six days —
> all signed off as detailed in the "Release checklist" handbook entry.
>
> **task-3** — The platform lists one workflow: **chinook-assistant**.

**Matches the catalogue's shape** — a `# Report` with one section per source
worker, each visibly using its own tool. Two of the three answers are also
correct. The other two facts the run produced are findings.

### Finding 1 — the honest hole

DuckDuckGo was rate-limiting this machine when the brief ran, and `web_search`
reported it in words. The worker **quoted the refusal and answered nothing
else**, which is exactly what the skill demands and the opposite of what an
unsteered worker would have done: a model with no instruction and a failed tool
has only its own weights left, and a brief that quietly becomes a recollection
is indistinguishable from a real one at the point where someone acts on it.

That is the strongest argument this gallery has for ticket 16: the section that
stayed honest is the section a *skill* was steering.

### Finding 2 — the platform cannot see its own gallery

`platform_list_workflows` reported **one** workflow, with twenty-four package
directories on disk. It is not a bug in the tool: `visible_to_platform_tools`
hides any envelope carrying `"published": false`, and every gallery example
sets it — a convention batch A inherited from the templates.

So the twenty examples are invisible on the customer surface, and by the same
gate invisible to the project knowledge catalogue that is built from the same
predicate. Whether an example ships published belongs to ticket 07 (examples
ship in the wheel); the fact that it currently does not is gallery ticket 33.

### Re-confirmed live, not re-filed

`decisions` came back `{}`. Three subtasks were labelled and dispatched to
three different workers — the sections prove it, because each one used a tool
only its worker holds — and **which archetype ran is nowhere in the result**.
That is gallery ticket 17, seen again on the graph that most needs it: with
heterogeneous *capabilities* rather than heterogeneous roles, "which worker
took this" is the difference between an answer from the handbook and an answer
from the open web.

## The handbook is the package

`knowledge/` holds four topics about a team that does not exist — a release
checklist, an on-call rota, three support desks, and the gallery's own rules.
Fictional on purpose, exactly as `knowledge-lookup-qa` argues: every figure in
an answer is either in these files or invented, with no third possibility, so
a correct answer has demonstrably been *fetched*. "Seven items" and "six days"
are both in `release-checklist` and in no model's weights.

The topics cross-reference each other by name, and `tests/` walks every
reference — progressive disclosure only pays if the next hop is fetchable.

## Tests

`tests/` asserts the fan-out is three workers, that each holds exactly one and
a *different* tool, that the three dispatch keys (slugified titles) are
distinct, that exactly one worker is the default, that no worker carries an
inert prompt while all three carry the skill, that the smoke question splits
into exactly three, and the store's own index and cross-reference contract. No
model is called.
