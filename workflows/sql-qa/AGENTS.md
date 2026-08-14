# SQL QA

Gallery example 17 of twenty — **text-to-SQL over a real database**, and the
only example in the twenty whose expectation is a *machine's*. The other
nineteen record an answer shape a reader judges; this one re-executes the SQL
the run stated and compares result sets.

| Node | One line |
| --- | --- |
| `in1` **Question** | where the question enters |
| `t-tables` **List tables** | `tool.sql-list-tables` — orientation, with row counts |
| `t-schema` **Table schema** | `tool.sql-get-schema` — columns, PK, and the foreign keys that are the JOIN rules |
| `t-query` **Run SELECT** | `tool.sql-query` — one read-only statement, capped at 50 rows |
| `answer1` **Analyst** | one ReAct agent holding all three |
| `out1` **Answer** | the sentence, and the query under it |

## Why this exists beside `chinook-assistant`

Same database, different half of the platform.

| | `chinook-assistant` | this package |
| --- | --- | --- |
| Tools | workflow-scoped `tool.chinook-*`, Python it ships in `tools/` | the platform's generic `prebuilt_sql` family |
| Configuration | the code knows where the database is | three nodes carry a `database` path |
| Graph | a full assistant — knowledge, web branch, 36 eval cases | six nodes and nothing else |

The generic family is the interesting one for a gallery, because it is the
"drop `data/business.sqlite` in a package and add three nodes" claim that
`prebuilt_sql.py`'s own docstring makes. This document is that claim, run.

**The database is the package's own copy.** `_resolve_database` jails a
configured path inside `workflows/`, so pointing at a sibling package's `data/`
would work today and break the moment either package moves — into a mount, into
a wheel, into an adopter's project. 1 MB is the price of a package that
survives being relocated.

## Smoke run

```
openstategraph run workflows/sql-qa "How many customers are in the database?"
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~4s:

> 59
>
> ```sql
> SELECT COUNT(*) AS cnt FROM Customer;
> ```

`decisions {}`, `attempts: 1`, `warnings []`. **Matches the catalogue.**

## The scorecard, which is the real acceptance test

```
openstategraph eval workflows/sql-qa
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, five cases, 23.9s total:

| | |
| --- | --- |
| execution accuracy | **100.0%** (4/4 answerable) |
| exact set match | 100.0% |
| refusal accuracy | 100.0% (1 unanswerable) |
| **overall** | **100.0%** — the CI gate |
| sql recovered | 100.0% |
| latency p50 / p95 | 5.04s / 5.91s |
| cost | not available — `RunResult` carries no token usage |

Verdicts: `correct=4`, `refused_correctly=1`. The hard case (`s04`, two joins
and a rounded sum) came back `USA, 523.06`, which is the gold query's own row.

### The query is evidence, not decoration

The agent is told to state its query in a fenced ```` ```sql ```` block after
the sentence, and that instruction is load-bearing. `evaluation/recovery.py`
recovers the SQL from the *answer*; an answer with no query scores `no_sql` —
not wrong, **unverifiable**, which is a distinct verdict on purpose. Delete the
instruction and the same correct answers score zero. `tests/` pins it.

The one case that must *not* show a query is `s05` — Chinook has no birth
dates, and a run that queries anything at all there is graded
`should_have_refused`. The prompt says so explicitly: no query, no block,
because there is nothing to show.

## The gap this example found

**The three SQL Explorer atoms have no canvas half.** `SQL_EXPLORER_TOOLS` is
registered in `api/registries.py` and runs perfectly — but no TypeScript node
definition declares `tool.sql-list-tables`, `tool.sql-get-schema` or
`tool.sql-query`, so they are absent from `port_specs.json`, absent from the
palette, and there is no card carrying the `database` field the tools read.
This `workflow.json` was written by hand and **cannot be drawn**.

`validate` says `VALID` because `KNOWN_PREFIXES = ("tool.", "function.")`
waves through any `tool.*` id — the check that would have caught it is the one
that does not look. Gallery ticket 30.

## Tests

`tests/` asserts the three atoms are generic (not `tool.chinook-*`), that all
three land on the one agent, that every configured path resolves through the
tool's own `workflows/` jail to this package's own file, that the prompt still
asks for the query, and that every gold query still returns exactly the rows
committed beside it. No model is called.
