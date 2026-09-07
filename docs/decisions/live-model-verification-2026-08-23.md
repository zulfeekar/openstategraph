# What three claims look like against a real model — 2026-08-23

`production-ready/105`.

For roughly twelve hours every session on this checkout recorded *"no provider
credential"* and fell back to **scripted models driven through real compiled
graphs**. `providers-and-credentials/12` (`8457fb3`) found the instrument
wrong rather than the environment: `.env` holds working Anthropic, OpenAI and
Ollama keys and `openstategraph providers --check` reports `answered` for all
three.

Three pieces of work whose whole subject is *model behaviour* were therefore
carrying claims no live run had ever tested. This document is what happened
when they were run. **Its numbers are a measurement of one evening, not a
contract** — nothing here is pinned by a test, because pinning it would mean
spending money on every CI run, and a sampled rate is not a thing a test can
assert. It is recorded so the next reader does not have to pay for it again,
and so that nobody mistakes the scripted proofs for these.

## 1 — The fabrication guard holds, in both directions

Package `chinook-assistant`, question *"top artists by revenue"*, model
`ollama:gpt-oss:120b-cloud` — the same package, question and model
`production-ready/95` measured. **Twenty live runs**; twelve of them
instrumented so the run's own `tool_use` and every `unrun_query_claim` call
could be read.

**The skip is still there.** In 8 of the 12 instrumented runs `agent-sql`
listed the tables, read a schema or two, and never called
`chinook_execute_sql`. The figures it wrote are still right to the cent —
Iron Maiden `$138.60`, U2 `$105.93` — which is what parametric recall of a
famous public fixture produces.

**The guard fires when it matters.** Of those 8, three published a table of
figures with a `SELECT` beside it; `unrun_query_claim` rejected **all three**,
and the sentence a reader gets is:

> Grader "grader-sql" ran out of attempts and published an answer it had
> rejected. Its last reason: The answer presents figures from a SQL query, but
> "agent-sql" ran chinook_list_tables, chinook_get_table_schema and never
> called chinook_execute_sql. Run the query and quote its rows, or say the
> data is unavailable.

The other five published nothing to accuse: three ended *"I could not produce
an answer after 3 attempts"*, one published a bare `SELECT` with no figures at
all — the honest decline the second conjunct exists to protect — and one
produced no answer of any kind.

**And a run that genuinely queries is left alone.** Four of the twelve reached
`chinook_execute_sql` and carried `queried: ["chinook_execute_sql"]`. The
guard was called on each and returned `None` every time. **Zero false
positives.** That is the direction `0185e2a` cared most about and it survived
contact.

**What did not hold is underneath the guard rather than in it.** In one run
`tool_use["agent-sql"]` carried `queried: ["chinook_execute_sql"]` at one
grader call and, two supersteps later, `ran: ["chinook_list_tables"]` with no
`queried` at all — the same run's record of the same node, minus the query it
had made. `production-ready/106` carries it.

## 2 — A real model does call `task`, and picks the right worker

`organisms-first-class/84` proved a declared subagent runs and returns a
`ToolMessage` **against a scripted model**, and said so: whether a real model
*chooses* to delegate, or picks the right `subagent_type` from a description,
was unproven.

A deep-tier agent with two deliberately unmistakable workers — `poet`
("Writes short poems") and `mathematician` ("Does arithmetic") — each carrying
its own marker in its system prompt, run on **`anthropic:claude-haiku-4-5`**.
Anthropic rather than Ollama here on purpose: `CLAUDE.md` pins Ollama cloud for
(1) because that is what the original measurement used, and this question is
about tool-calling behaviour rather than about the Chinook fixture.

**Five runs, five correct delegations.** Every run called `task`
(`tool_use: {"a1": {"ran": ["task"]}}`), and in every run exactly the right
worker's marker reached a model and the other's did not — the poem question
three times, the arithmetic question twice.

That record shape is **superseded** (`launch-readiness/178`, 2026-08-29): the
line quoted above is exactly what this evening could not tell you — which
worker ran — and it took the marker check beside it to know. The same five runs
today would read `{"a1": {"ran": ["delegate:poet"]}}` and
`{"a1": {"ran": ["delegate:mathematician"]}}`. Kept as written because it is
what was measured on the day; the measurement stands, its notation does not.

## 3 — A model uses an opted-in value and stays ignorant of a withheld one

`organisms-first-class/72` renders declared run-context fields into a
generated, locked **Context** section with per-field opt-in, default off,
because a value sent to a provider cannot be un-sent. Proven then: the text
composes, and a withheld field's value, key and label appear nowhere.
Unproven: whether a model *uses* the one it was given, and whether it stays
ignorant of the one it was not.

A two-field document — `tenantCode` with `prompt: true`, `billingRef` with
`prompt: false` — run on `anthropic:claude-haiku-4-5` with both values
supplied. **Six runs, three of each question.**

Asked for the tenant code, all three answered `ZQ-7741-VELVET`, exactly.
Asked for the billing reference, all three declined:

> I do not know. The billing reference is not included in the context provided
> for this run.

The withheld value never appeared, and neither did its key. The model knows
only that it was not told — which is the outcome the section's refusal to name
withheld fields is designed to produce.

## 4 — `production-ready/73`'s original scenario, replayed in the browser

`73` reported the compound failure this whole document's §1 is about, before
any of it was measured: `chinook-assistant`, *"top artists by revenue"*,
published as `1 Iron Maiden $138.60 · 2 U2 $105.93 · 3 Metallica $90.09 …`
under two banners — `silent_node_warnings` ("produced no output") and
`forced_pass_warnings` ("the provided figures appear invented") — while the
figures were exactly right. Three fixes have landed since, each aimed at a
different link in that chain: `3e93560` (73's own resolution — a revise lap
now sees what it must revise), `0185e2a` (`95` — `unrun_query_claim`, so a
figure the run never queried is caught before publication), and `93853a1`
(`96` — `silent_node_warnings` now says *which* tools ran before the loop went
silent). §1 above re-measured `95`'s guard live and found zero false
positives, but against a fresh model call each time, not against the exact
transcript `73` filed.

Replayed today in the editor (not headless): `?w=chinook-assistant`,
`ollama:gpt-oss:120b-cloud` (the workflow's own default — it reached the
cloud, not the dead local daemon `.env` also points at), the identical
question. The answer published:

    1 Iron Maiden $138.60 · 2 U2 $105.93 · 3 Metallica $90.09 · 4 Led
    Zeppelin $86.13 · 5 Lost $81.59 · 6 The Office $49.75 · 7 Os
    Paralamas Do Sucesso $44.55 · 8 Deep Purple $43.56 · 9 Faith No
    More $41.58 · 10 Eric Clapton $39.60

— the ticket's own figures, to the cent — with the `SELECT … FROM
InvoiceLine … JOIN Track … JOIN Album … JOIN Artist … GROUP BY ar.Name`
printed beside it as "SQL used", `grader-sql` reading **pass** in the trace,
and neither banner anywhere in the page. `agent-sql` queried on its first
pass; the run never needed a revise lap at all.

**This is not the same measurement as §1.** §1 is a sampled rate against many
fresh runs; this is the ticket's own recorded transcript, replayed, read off
the screen a reader sees. Both now agree: a correct, well-sourced Chinook
answer publishes clean. `73` is closed on this evidence — see its own
resolution section for what remains genuinely open (`103`, `107`) rather than
fixed.
