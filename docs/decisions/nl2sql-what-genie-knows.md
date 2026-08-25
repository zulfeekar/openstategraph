# What Genie knows that we do not

**Status:** research concluded, 2026-08-25. Feeds `launch-readiness/68`.
**Verdict:** adopt the *shape* both sources independently arrived at. Do not
adopt either implementation.

Two lines of research ran in parallel and did not know about each other: one
read Databricks' own documentation, one read a production system built by a
different team against the same lakehouse. They converged on the same answer,
which is the strongest signal in this document.

---

## The convergence

**Databricks ranks the techniques that make NL2SQL accurate, explicitly, in
this order** (`docs.databricks.com/aws/en/genie/best-practices`, re-fetched
independently rather than taken on an agent's report):

1. **SQL expressions and metric views** — business semantics defined *as SQL*
2. **Example SQL queries** — teaching the model how to handle ambiguity
3. **Text instructions** — *"only as a last resort"*

Their sentence: *"Structured definitions through SQL are more reliable and
maintainable than plain text guidance."*

**The CPL backend arrived at the same conclusion by building it.** Its
`skills_v2/` is eighteen **lenses**, each a directory rather than a class, and
each carrying a hand-authored `SCHEMA.yaml` that declares — as data — one
canonical table, its date columns and default, its join axes, its grain, its
quantity column and the aggregation pattern for it, its typical data lag, and a
list of forbidden idioms. Three middleware gates read that file: a grounding
gate, a schema-conformance check, and a result reviewer. A test pins it.

The file says so itself, and the line is the whole thesis:

> DO NOT edit to make a failing query pass — the schema is the authority, the
> query is wrong.

That is category 1 of the Databricks ranking, implemented. Two independent
sources, one documented and one running, both say the same thing: **move
knowledge out of the prompt and into a machine-checkable declaration.**

## Where that leaves us

`cpl-nl2sql`'s domain knowledge is almost entirely in `agent1`'s rules prompt
and in a hand-written entity dictionary. That is category 3 — the last resort —
and it explains a class of failure we have been treating as separate bugs:

- A prompt rule is a *request*. The model may decline it and nothing notices.
  Thirteen of our twenty-two SQL rules are prompt-only; the validator enforces
  the rest, which is why the validator is the part that works.
- `launch-readiness/67` — the dwell time that doubled between two runs of an
  unchanged graph — is exactly what an unpinned aggregation looks like. A
  `SCHEMA.yaml` declaring the quantity column, the grain, and the aggregation
  pattern makes that variance either impossible or loud.
- The Fujairah bounding box in our entity dictionary is unverified world
  knowledge sitting upstream of a number a trader would act on. In the lens
  shape it would be a declared, checkable fact rather than a paragraph.

## Entity resolution — the finding worth the whole exercise

The ticket asked whether a mature system resolves `Mongstad` with
`LIKE '%Mongstad%'`, and said plainly that *yes* would be as useful an answer as
*no*, because it would tell us nobody has solved it.

**It is no.** CPL does not fuzzy-match. It holds canonical values (a
`SELECT DISTINCT` over the allowed tables) in a cache, resolves
**type-aware** — a country is not a port is not a vessel class — and
**direction-aware**, distinguishing a load port from an unload port. Typo
handling is its own module rather than a prompt instruction. A value that does
not resolve produces a **clarification request, not a guess**.

That last clause is the one to steal outright. Our failure mode is a confident
wrong answer; theirs is a question back. Ours is worse, and it is a design
choice rather than a bug.

## What not to lift

- **Their implementation.** Redis, their MCP tool surface, their agent loop.
  We are a compiler onto LangGraph; they are a service. The pattern transfers,
  the plumbing does not.
- **Eighteen lenses.** They earned those incrementally. We would be guessing.
  Start with the two or three our demo questions actually touch.
- **Databricks' managed MCP servers — not yet.** They are real and the
  endpoints are documented (`/api/2.0/mcp/genie/{space_id}`,
  `/api/2.0/mcp/sql`, `/api/2.0/mcp/functions/...`, OAuth on-behalf-of-user),
  but the page says **"This feature is in Public Preview."** A demo must not
  depend on an endpoint that may move. Worth a spike, not a dependency.

## The correction this document exists to record

The web researcher reported that *"Genie does not use vector indexing; it reads
Unity Catalog metadata directly,"* and recommended abandoning the vector-search
approach on that basis. **The cited page does not say that.** It says Genie uses
Unity Catalog column names and descriptions; the retrieval mechanism is
undocumented. The positive claim survives — curate UC metadata, it is read and
it matters. The negative one does not, and it was the load-bearing half of a
recommendation to gut `prefetch1`.

Re-fetching the page took one call. Not re-fetching it would have cost a
working component on a claim nobody had checked.

## What we would build

A `SCHEMA.yaml` per lens, in the package beside `workflow.json`, declaring the
canonical table, date columns and default, join axes, grain, quantity column
and aggregation pattern, and forbidden idioms. Our SQL validator already parses
the AST with sqlglot; it grows a source of truth to check *against* instead of
the general rules it enforces today. Entity resolution becomes a lookup against
distinct values with a clarification path, replacing `LIKE`.

Each of those is its own ticket, behind its own control run. `~/osg-demo/` is
demo-critical: enhancements only, never revert.
