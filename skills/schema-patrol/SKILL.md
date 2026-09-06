---
name: schema-patrol
description: A recurring sweep that keeps a data package's declared knowledge honest against the warehouse it queries. Reconciles the five descriptions of one warehouse a package carries — fact, index, knowledge, skill, rules — reports where they disagree, and proposes a change without ever writing one. Run it as a daily round from cron, as a CI step, or by hand before a demo. Use it whenever a package's lens/declaration files, its retrieval index, its validator or its warehouse map may have drifted apart, and whenever an agent answers a question with a table its own validator then refuses.
---

# Schema patrol

Keep the descriptions of a warehouse honest by comparing them to the warehouse.

This is a repository skill, not an agent feature. It assumes nothing but the
ability to read files and run shell commands. Every path below is real; check
one if you doubt it. Any coding agent can follow it, and the mechanical half
runs with no agent at all.

## The defect this exists for

Three consecutive live failures traced to one vessel dimension,
`shipping.dim_vessel_latest`. The retrieval index told the agent to join it.
No declaration permitted it. The agent obeyed the index, the validator
refused, the agent invented a column to replace what the join would have
given it, ran out of attempts, and the user got a generic non-answer.

It was found by a human reading three traces. Nothing checked.

**Two descriptions of one warehouse drifted apart and nothing noticed.** That
is the class. It is not specific to vessels, to Databricks, or to this
package, and it recurs, which is why the answer is a patrol rather than a fix.

## The five sources, and which one is the authority

A data package carries five descriptions of one warehouse:

| # | Source | Where it lives | What it is |
|---|---|---|---|
| 1 | **Fact** | the catalog, plus a verified query | what is **actually** true |
| 2 | **Index** | the retrieval index the agent searches | what the agent is **told** |
| 3 | **Knowledge** | a hand-written warehouse map | what we **understand** |
| 4 | **Skill** | the declaration files (YAML blocks) | what is **declared** |
| 5 | **Rules** | the validator, and the prompt rules | what is **enforced** |

**Fact is the authority. The other four are claims about it.** Every check
below is a claim-set measured against ground truth, or against another claim
where the disagreement itself is the bug.

## What the script decides, and what the reader decides

This split is the whole design, and collapsing it is how a package acquires
declarations nobody believes.

**The script decides what is mechanical and provable.** Does this table exist.
Does the index name it. Does any declaration permit it. Do the two sides of a
join carry the same type. Is this column still in the catalog. Deterministic,
no model, no judgement, exits non-zero when something disagrees. Runnable from
cron or CI with no agent in the loop.

**The reader decides everything that needs judgement.** Is this table a
*dimension an existing lens should join*, or a *fact table deserving its own
declaration*? Is it infrastructure that should never be queried at all? Is
this type mismatch a trap worth documenting or a bug worth fixing? No scan can
answer those, and a scan that pretends to is worse than no scan.

## The rule this skill insists on

> **The patrol proposes; a human or an agent with judgement disposes. Nothing
> is auto-written into a rule file from a scan.**

The script prints a *proposed change* and stops. It never edits a declaration,
a rule, or the map — not even an obviously-correct one.

Why, stated plainly so nobody optimises it away: a rule silently rewritten by
a scan is a rule nobody can trust. The entire value of a declaration is that
it means something — that a human looked at a table and decided it belongs. A
declaration appended by a nightly job means only *the scan saw it*, which is
the same information the scan already had. Auto-writing would convert the
declaration layer from a set of decisions into a second copy of the catalog,
and a lens that declares everything reachable declares nothing.

## The five checks, in the order that has drawn blood

| Check | Compares | Finds | Severity |
|---|---|---|---|
| **1** | Index vs Skill | told to use it, forbidden to use it | **exit 1** |
| **2** | Skill vs Fact | a declaration the warehouse denies | **exit 1** |
| **3** | Index vs Fact | the agent is told something stale | **exit 1** |
| **4** | Rules vs Skill | decoration, or a rule with no source | report |
| **5** | Knowledge vs all | the map disagrees, or was never verified | report |

**1 — Index vs Skill.** The highest-severity finding there is, and the reason
this exists. Every table the index names in *any* field is checked against
what the declarations permit. **Including every table named inside a
`usage_hint`** — that is the one that bit us, because a `usage_hint` is an
instruction, not a description, and the agent follows it literally.

**2 — Skill vs Fact.** A declared table or column the catalog does not have,
or a declared role its real type contradicts. The validator would be enforcing
a fiction.

**3 — Index vs Fact.** The index describes a column that no longer exists, or
sample values that no longer match. Being told something stale is worse than
being told nothing.

**4 — Rules vs Skill.** Both directions are findings. **A declaration nothing
enforces is decoration** — it reads as a guarantee and is not one. **A check
with no declaration behind it is a rule with no source** — usually a hardcoded
list quietly disagreeing with the declarations it should be reading.

**5 — Knowledge vs everything.** The map claims something the other four
contradict. Plus the two standing lists only this source can produce, because
a good map tags each claim with its provenance:

- claims tagged **verified by query** are re-checked, or listed for
  re-checking when the patrol is offline;
- claims tagged **inferred — not verified** are listed as a standing to-do.
  An inference that quietly became load-bearing is exactly how a hand-drawn
  coordinate box ended up upstream of a number a trader would act on.

### Why only 1, 2 and 3 exit non-zero

Checks 4 and 5 need judgement, and their findings usually have a good reason —
a field the rules read generically, a map claim awaiting a query. So does one
finding *inside* check 1: **an existing table no declaration mentions is
normally correct.** Most of a warehouse is infrastructure, staging and older
versions that answer no user question. Failing on those would mean 75 findings
on a healthy package.

**A check that fails for acceptable reasons gets ignored, and then it protects
nothing.** That is the reasoning, and it is worth defending against the urge to
make everything a gate.

The one refinement worth knowing: a type mismatch the declaration **already
documents as a trap** is downgraded to a note. The team knows, it is written
down, and failing on it would train everyone to mute the patrol.

### Sources that do not exist

**Not every package has all five, and that is normal, not an error.** A
missing source skips its check, and the skip is *printed* — `[skip]`, never
`[ok]`, with the reason. Silence about a skipped check is the same defect this
whole thing exists to prevent.

## Running it

```
python3 patrol.py <package-path>
python3 patrol.py <package-path> --knowledge path/to/warehouse-map.md
python3 patrol.py <package-path> --refresh    # recapture the fixture first
python3 patrol.py <package-path> --json       # machine-readable findings
python3 patrol.py <package-path> --quiet      # failing findings only
```

Exit codes: `0` clean, `1` a failing finding, `2` the patrol could not run.

**It works on any package of this shape.** The package path is an argument and
the declaration files are discovered, not named: a fixture is a JSON file
carrying a `catalog` key, a declaration is a fenced YAML block naming a
`canonical_table`, a rules file is the code and prose beside them.

**It runs offline against a committed fixture**, so CI needs no warehouse and
no credentials. `--refresh` recaptures the fixture — and it does so by invoking
**the package's own fixture generator**, which the patrol discovers. The patrol
deliberately does not capture warehouse facts itself: the credentials, the
catalog name and the index name are the package's business, and a second
capture path is a second source of truth. In the package this was built
against the generator is
`scripts/refresh_warehouse_facts.py` and the fixture is
`data/warehouse_facts.json`. A package that has neither should add them there,
not here.

### Running it as a round

Pick one; do not run all three.

**Cron, daily.** Mail the output; the exit code decides whether it is urgent.

```sh
0 7 * * *  cd /path/to/repo && python3 skills/schema-patrol/patrol.py \
             workflows/<package> --knowledge docs/warehouse-map.md --quiet
```

**CI, per push.** The fixture is committed, so this is fast and hermetic.

```yaml
- name: schema patrol
  run: python3 skills/schema-patrol/patrol.py workflows/<package> --quiet
```

CI catches the *declaration* drifting. It cannot catch the *warehouse*
drifting, because the fixture is frozen — so refresh the fixture on a schedule
(the one job that needs credentials) and commit the diff. **A diff in the
fixture is the point**: it is the warehouse changing under the declaration
layer, made visible before a demo finds it.

**An agent, invoked daily.** Run the script first, then act on what it printed
using the judgement half of this skill: for each finding, decide, edit by hand,
and re-run. An agent doing this must still obey the rule above — it reads the
findings, it does not pipe them into a file.

### A good run versus a noisy one

A **good** run is short. Checks 1–3 say `ok` or name two or three things a
person recognises. The notes are stable between runs, and each one is either
being worked on or has a recorded reason.

A **noisy** run is the failure mode to watch for, and it has three usual causes:

1. **Nothing is exempt.** The package never recorded which tables are
   deliberately not lenses. Fix it once, in the package, under a `## Not a
   lens` heading with the reason — the patrol reads that and stays quiet.
2. **The same note every day for a month.** Either act on it or record the
   decision. A note nobody acts on trains everybody to skim.
3. **The parser is wrong, not the package.** This one is real: an early draft
   of `patrol.py` checked declared columns against the canonical table only,
   and reported four correct declarations as broken because their columns live
   on a joined dimension. **A parser bug reported as a package bug is worse
   than no patrol.** Before filing a finding, open the file it names.

## The worked example: `dim_vessel_latest`

The case the patrol was built from, end to end.

**What the index said.** Index rows for the vessel-class glossary named
a fully qualified dimension table — in `glossary_maps_to`, in
`description`, and in a `usage_hint`, which the agent reads as an instruction.

**What the declaration lacked.** No lens declared that table, as a canonical
table or as a join. The validator's allowed set was built from the lens files,
so the table was not permitted.

**What the user saw.** The agent wrote SQL joining the dimension it had been
told to use. The validator rejected the table. The agent tried again, invented
a column on the permitted table to stand in for what the join would have
given it, was rejected again, exhausted its attempts, and returned a generic
non-answer. Three separate live questions failed this way before anyone read
the traces.

**What the fix was.** Not a prompt change. The dimension was declared, by
hand, on the lenses that legitimately join it — with its role (`dimension`),
its join predicate, and its traps written down. A human decided *dimension,
not fact table*; that decision is the thing the declaration records, and it is
exactly the decision a scan must not make for you.

**What catches it now.** Check 1. Any table the index names — including inside
a `usage_hint` — that no declaration permits is a failing finding, on every
run, before a user meets it.

## A clean run, verbatim

Against a private data package on 2026-08-25, after the dimension was
declared. Checks 1
and 3 are clean — **the finding the patrol was built for is gone**, which is
the demonstration that it reads the package correctly rather than that it has
nothing to say.

```
[note] check 1  INDEX vs SKILL    told to use it, forbidden to use it
        - (existing-but-unplaced) 75 tables
          exist in the catalog, named by no declaration and by no index row
          [...]
          proposed: no action required — an unplaced table is usually correct.

[FAIL] check 2  SKILL vs FACT     a declaration the warehouse denies
        - (documented-type-mismatch) movements_latest.vessel_imo = dim_vessel_latest.imo
          that lens joins INT to LONG — already recorded as a trap in the declaration
          proposed: no action
        - (contradictory-type) idle_events_v1r2.IMO = dim_vessel_latest.imo
          'vessel_idle_periods' joins INT to LONG — the equality is legal, but a value
          overflowing the narrower type is silently lost, and nothing warns
          proposed: record the mismatch as a trap in vessel_idle_periods.md, or declare
          an explicit cast.
        - (contradictory-type) ais_sampled.IMO = dim_vessel_latest.imo
          'vessel_positions' joins INT to LONG — [same]

[ok] check 3  INDEX vs FACT     the agent is told something stale
        - none

[note] check 4  RULES vs SKILL    decoration, or a rule with no source
        - (declared-but-unenforced) forbidden
          declared by 8 declaration(s) and named nowhere in the rules layer
        - (declared-but-unenforced) join_axes
          declared by 8 declaration(s) and named nowhere in the rules layer

[note] check 5  KNOWLEDGE vs all  the map disagrees, or was never verified
        - (inferred-not-verified) 4 claim(s)
        - (verified-needs-recheck) 8 claim(s)

2 failing finding(s). The patrol proposes; a human or an agent
with judgement disposes — nothing above has been written to any file.
```

Read what that says about the package, because it is the model for reading any
run:

- **Check 1 is clean.** The dimension is declared. The 75 unplaced tables are
  a report and correctly not a failure.
- **Check 2 fails, and it is right to.** Three lenses document the INT/LONG
  `imo` mismatch as a trap and are downgraded to notes; **two do not**, so
  those two are failures. That is a genuine gap the patrol found on its first
  real run, and it is exactly the shape of the original defect: knowledge that
  exists in three files and is missing from two.
- **Check 4's two notes are honest.** `forbidden` and `join_axes` are declared
  by all eight lenses and enforced by nothing. Either write the checks or drop
  the fields — but that is a decision, which is why it is a note.
- **Check 5 lists rather than concludes**, because the patrol runs offline and
  cannot re-run a `SELECT`. Saying so is the point; a claim it cannot check is
  a claim it must not bless.

## Extending the patrol

Add a check when a *sixth* kind of disagreement has actually cost something —
not before. Each check is one function taking parsed sources and returning
findings; a finding carries its kind, its evidence, and its proposal. Put a new
kind in `FAILING_KINDS` only if a run that reports it is a run somebody must
stop for. Everything else is a note, and notes are how this stays trusted.
