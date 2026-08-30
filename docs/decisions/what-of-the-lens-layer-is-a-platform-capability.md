# What of the lens layer is a platform capability

Source: a private NL2SQL package (not modified by this
review). It produced four things during its build. One (`dbf5f87`, the
`skill` port connection cap) is already in OpenStateGraph. This document
covers the other three: the lens files (`skills/lenses/*.md`), the SQL
validator (`tools/sql_validator.py`), and the failure translator
(`functions/execute_sql.py`).

## Recommendation, in one sentence

None of the three needs new platform machinery: the lens files are
Databricks-schema-shaped package content, the validator is a package
function that already fits an existing extension point (`guard.check`,
shipped `78c0bc0`) with zero engine change, and the failure translator's
vocabulary is the package's own and belongs nowhere else.

## 1. The lens files — package-local

**Question asked:** is a lens a general idea (a machine-checkable
declaration of what a data source contains) or a SQL-specific one?

The general idea — "declare what a data source contains so code can check
against it" — is real, but the *fields* are not general: `canonical_table`,
`date_columns` + `default_date_column`, `join_axes`, `grain`,
`quantity_column` + `quantity_aggregation`, `resolve_before_filter`,
`typical_lag_days` are a schema for **one relational-warehouse SQL
question-answering task**. A workflow that calls an API, greps logs, or
walks a document store has no `join_axes` and no `quantity_aggregation`.
Generalizing this into a platform type would mean inventing a lowest-common-
denominator schema nobody has asked for, which CLAUDE.md's "Small, named
packages" rule and the eval-vs-graph section both warn against: build for
the shape that exists, not the shape imagined might exist. **Decided
against:** a `dataSource` or `lens` node/field-schema family in core. There
is exactly one consumer of this shape in the repository, and it is package
content sitting next to the `tools/*.py` that reads it — the same trust and
portability tier CLAUDE.md already assigns to a package's own Python.

## 2. The validator — already covered, no new capability

**Question asked:** does this belong to the `guard.check` family already
shipped (`78c0bc0`)?

Yes, exactly. `backend/openstategraph/compile/node_runtime.py`'s
`_guard_check` (`workflow_compiler.py:105 GUARD_CHECK_TYPE`) already
implements precisely this shape: a `function.*` node (contract `fn(text:
str) -> str`, the same contract every discovered function already has) is
consulted on a `pass`/`revise` conditional edge, an empty return is a pass, a
non-empty return is both the revise reason and the feedback sent upstream,
and it is registered — "extend by registering, never by editing the engine"
— through `services.functions`, the same registry `function.*` nodes already
use. `sql_validator.py`'s sqlglot-AST checks (entity resolution, known
tables, declared joins, declared date columns, pinned aggregation) are
package logic that would sit behind `function.validate_sql` and wire as a
`guard.check` node with zero engine change. **Decided against:** a new
`SqlGuard` or `SchemaGuard` node type. `guard.check` is not SQL-shaped at
all — it takes a string in and a string out — so a SQL-specific subtype
would only narrow an interface that is already general enough.

One observation worth recording rather than acting on: the package's actual
workflow wires its validator behind `route.grader` (a **model call** reading
"VALIDATION: PASS" out of the validator's own text) rather than
`guard.check` (which would call the same Python function directly, for
free, no model). That is a package wiring choice made before `guard.check`
existed on this map, not a platform gap — see the documentation ticket
below for the one place this is worth writing down.

## 3. The failure translator — package-local

**Question asked:** is leaking internal check names to a user a general
concern, and does this generalize?

The concern is general — CLAUDE.md's "Read a model's answer tolerantly;
trust it strictly" section already exists because of exactly this class of
bug. The *fix* is not general: `_FACET_PLAIN` maps `sql_validator.py`'s own
facet strings (`resolve_before_filter`, `date_column`,
`unknown_table_for_lens`, `cardinality`, ...) to plain English. Those facet
names are the package's private vocabulary — a different package's
validator would invent its own — so a platform-level translator would need
either a fixed enum of facets (impossible; every validator's checks differ)
or a generic "hide anything that looks like an internal id" heuristic
(unreliable and exactly the kind of confident-looking guess CLAUDE.md
rejects elsewhere). **Decided against:** a `guard.translate` node or a
`FailureTranslator` base class. The right owner of "what does check id X
mean in English" is the author of check id X.

What *is* worth noting, because it changes the size of the problem: the
`guard.check` node itself does not have this bug. Its `run()` always
returns `"outputs": {node_id: candidate}` — the upstream candidate text —
never the failure `reason`, even when the attempt budget is exhausted and
the branch is forced to `pass`. The reason is confined to `feedback` (fed
back into the revision loop) and `verdicts[node_id]["reason"]` (a structured
field, not prose glued into the answer). The leak in that package
(`launch-readiness/74`) happened because `gate1` was a `route.grader`
relaying the validator's *raw text* as its own candidate, so an exhausted
budget forced that raw text — check ids and all — downstream as the
"answer". A `guard.check` node wired the same way cannot reproduce this
specific bug, because it was designed not to carry `reason` into `outputs`.

## What generalizes

Nothing new. `guard.check` already is the platform capability this map was
checking for; it shipped before this package was built and this package
simply did not use it for its validator.

## Ticket filed

One documentation gap, not a platform capability: nothing in
`docs/building-an-atom.md` says "a deterministic pass/fail check belongs on
`guard.check`, not a model-relayed `route.grader`", and the one existing
example of getting this wrong is exactly the failure this document's
section 3 traces. See `.scratch/launch-readiness/tickets/75-...md`.
