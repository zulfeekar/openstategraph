# Testing a second brain

A knowledge store is prose your agents treat as **the reference**. That is the
whole point of it — and it is also the risk, because a wrong sentence in
`knowledge/invoice.md` is not a hallucination any more, it is a fact the model
was handed. So the store needs checking the way code needs checking.

This page is the procedure. What to build, what to run, what good looks like,
and — the question nobody else answers — **how to tell a stale doc from a wrong
one**, because the fixes are opposite.

Everything here uses the CLI and the HTTP API you already have. There is no
test harness to install: the curation contract already records who wrote each
doc, what it was written from, and whether that source has moved since.

- What a second brain *is*, and the artifact's lifecycle:
  [Using it in your project → `knowledge/`](adoption.md#knowledge--generated-then-claimed)
- Why it is shaped this way: [`decisions/knowledge-architecture.md`](decisions/knowledge-architecture.md)
- Where the build button lives: [`decisions/build-time-affordances.md`](decisions/build-time-affordances.md)

---

## 0. What a project's second brain is

A **package** has one store — `workflows/<slug>/knowledge/` — and its agents
read it through `knowledge_lookup`, on demand, one topic at a time.

A **project** does not have a store of its own. There is no
`workflows/knowledge/`, and there is deliberately never going to be: a store is
only worth writing where an agent is bound to read it, and binding is per
package. A project's second brain is the **union of its packages' stores**,
plus a catalogue held by whichever workflows can actually see the project.

That last part is a source like any other. Sources are recognised from the
wiring — a `tool.sql-*` node's connection field means "a database is a source
here"; a mount means "a child is"; and a **platform tool**
(`tool.platform-list-workflows`, `tool.platform-describe-workflow`) means
**"the project is"**, because a workflow holding one can enumerate and describe
every package on the platform. Its catalogue docs land in its own `knowledge/`
like everything else.

| Builder | Recognised from | Topics | The doc says |
| --- | --- | --- | --- |
| `sql` | a SQL tool's `database` | one per table | what the table means, its JOINs, its caveats |
| `root` | `workflow.subgraph` | the children it **mounts** | *send the question there* |
| `project` | a `tool.platform-*` node | the packages those tools **show**, minus the mounts | *this exists, and here is when it is the wrong answer* |
| `codebase`, `explorer` | package code / other read-only tools | a concept map | openwiki-shaped concept pages |

Two things follow, and both are worth knowing before you go looking for a bug:

- **A mounted child never gets a catalogue doc.** It gets the strictly better
  routing doc instead, and the two topic sets are partitioned so a gateway's
  build reports no collisions.
- **The visibility gate differs between `root` and `project`, on purpose.** A
  mount compiles its child as a subgraph and consults neither `published` nor
  `hidden`, so a mounted draft still gets a routing doc. A platform tool
  enforces both, so a draft or hidden package gets **no** catalogue doc — an
  agent must never hold a pointer to something its own
  `platform_describe_workflow` will then refuse to describe.

**Pointers, not copies**, at every level. A catalogue or routing doc says what
another workflow is and where depth lives; it never carries that workflow's
table-level detail upward. Copying detail up recreates context bloat one level
up, and rots the moment the child rebuilds.

---

## 1. Build it

```bash
openstategraph knowledge build ./workflows/chinook-assistant
```

Or the **Build second brain** button on the Knowledge card in the editor —
same code path, same seam. Building is build time: nothing in a compiled graph
can reach a builder, so a customer run can never trigger one.

The report is four lists, and each one is a different message:

| | Means | Do |
| --- | --- | --- |
| `written` | generated, or regenerated over a doc this builder owns | read them (§3) |
| `skipped` | you own that file — no marker, so it was left alone | nothing; that is the contract working |
| `collisions` | a topic another builder already owns; refused rather than overwritten | rename one source's topic, or decide which builder should own it |
| `warnings` | a source that was recognised and could not be opened, or a mount naming a package that will not load | fix the source and build again — a warning is never a doc |

Useful flags: `--source sql` runs one builder; `--instruction "focus on
billing; the fiscal year starts in April"` steers the agentic explorer;
`--model` picks the model that drafts the prose.

> **Regenerating is safe, and that is checkable rather than hopeful.** A doc
> with no generated marker is yours forever and is never overwritten. Prove it
> to yourself once: edit a doc, save, build again, and watch its topic move
> from `written` to `skipped`.

**Prove it on a scratch root first if you are experimenting.** Everything below
is destructive to generated docs:

```bash
export OPENSTATEGRAPH_WORKFLOWS_ROOT=/tmp/wfroot
```

---

## 2. Look at the index — it is what the model sees

```bash
openstategraph knowledge list ./workflows/chinook-assistant
```

```
- album — Album — a record representing a music album, answering "what is the album's ID, title, and which artist created it?"  [generated: sql]
- invoice — Invoice — a record of a customer's purchase, answering which customer bought what, when, and the total due.  [generated: sql]
- house-rules — Revenue is always net of tax.  [yours]
- track — Track — represents a single audio recording…  [generated: sql, STALE]
```

Three columns, three checks:

**The topic name.** This is the string an agent must guess. For SQL it is the
table name normalised, which is what a model reading a schema will try. If a
name here is not the name your agents would reach for, that topic is close to
unreachable.

**The hint.** The store's index tier is self-assembling: the hint *is* each
doc's first meaningful line. It is also the entire menu an agent gets when it
looks up a topic that does not exist. So read this list as a menu and ask: *if
I only had these sentences, could I pick the right one?* A hint like "This
document describes the Track table" fails that test; the generated form —
`<name> — <what it is and what it answers>` — passes it. A hand-written doc
gets its index line for free by starting with one sentence.

**The badge.** `[yours]` — no marker, hand-owned, never regenerated.
`[generated: <builder>]` — owned by that builder. `STALE` — see §4.

**Reaching the index does not require missing first.** `knowledge_lookup`
called with no topic (or an empty one) returns the same listing directly and
succeeds — a first-class call, not a side effect of guessing wrong. That is
what the tool's own description tells a model to do before it guesses a topic
name at all; gallery ticket 29 fixed the gap where the only route was through
an `Error:`.

Check the miss path too, because a wrong *named* guess is still the common
case in practice and must still answer with the same menu:

```bash
python3 -c "
from openstategraph.prebuilt_knowledge import ambient_knowledge_tool
tool = ambient_knowledge_tool('workflows/chinook-assistant')
print(tool.run(topic='sales').error)"
```

```
No knowledge for topic 'sales'. Available topics:
- album — Album — a record representing a music album, answering …
- artist — Artist — a table that stores unique musical artists …
…
```

A miss must answer with the menu, not a dead end — one wrong guess should cost
one tool round-trip. This also answers *"is the tool even bound?"*:
`ambient_knowledge_tool` returns `None` when the directory is empty, which is
exactly the rule the compiler applies.

### Coverage: is anything missing?

Compare the index against the source's own enumeration. For SQL that is one
line:

```bash
diff <(openstategraph knowledge list ./workflows/chinook-assistant | sed 's/^- \([a-z0-9-]*\).*/\1/') \
     <(sqlite3 workflows/chinook-assistant/data/Chinook_Sqlite.sqlite \
        "SELECT lower(name) FROM sqlite_master WHERE type='table' ORDER BY 1")
```

For a mount-holding or platform-tool-holding workflow, the equivalent question
is *"does every child I mount have a routing doc, and every package I can see a
catalogue doc?"* — and the build's own `warnings` list is the answer: a mounted
slug that will not load, or a package whose `workflow.json` will not parse, is
reported there rather than silently missing.

---

## 3. Read the docs — the part no tool can do for you

Generation is a model call. The output is plausible by construction; that is
exactly why it needs a reader. Three checks, in the order that finds problems
fastest:

**Follow the provenance footer.** Every generated doc ends with what the
builder actually looked at:

```
_Provenance: built from table Invoice of chinook-assistant/data/Chinook_Sqlite.sqlite (sqlite schema + sample)._
```

Open that. Any claim in the doc that the named source cannot support is
invented, and it is invented in the one place your agents will trust
completely.

**Check the relationships, not the prose.** The commonest generated error is a
JOIN stated backwards or a foreign key hallucinated between two tables that
merely share a column name. Those are cheap to verify against the schema and
expensive to leave in.

**Check that a pointer is a pointer.** A `root` or `project` doc that has
started listing another workflow's tables has copied instead of pointed. Delete
the detail; a doc that duplicates its child goes wrong the next time the child
rebuilds, and nothing will tell you.

Where the doc is wrong, **fix it in place and save**. The first save strips the
generated marker: human touch is human ownership, with no ceremony to forget.
The file is now yours, it will never be regenerated over, and it lands in git
as a diff someone can review.

---

## 4. Stale is not the same as wrong

This is the distinction that matters, because the two fixes are opposite and
the symptoms look identical from a distance.

Every generated marker stamps a hash of the **brief** the doc was written from
— the schema and sample, the child's topology, whatever the builder read.
Claiming a doc records that same hash in a trailing comment. The listing
recomputes the brief and compares.

| | Stale | Wrong |
| --- | --- | --- |
| What happened | the **source** moved after the doc was written | the source is unchanged; the **doc** misdescribes it |
| How you find it | the `STALE` badge, mechanically | reading it against its provenance (§3) |
| Is the doc wrong? | **unknown** — a new column may not affect a word of it | yes |
| Fix, if generated | rebuild the topic | rebuild only if the builder would now do better; otherwise edit and save |
| Fix, if claimed | re-read it against the new source, then save to re-record the hash | edit and save |

Three consequences worth stating out loud:

- **A stale badge is never a rewrite.** Nothing overwrites a claimed doc, ever.
  You keep the pen; you lose the ignorance.
- **Claimed docs go stale too.** That is deliberate. The commonest real failure
  is a hand-tuned doc that was right in March and describes a column that was
  dropped in June.
- **Agentic topics are never badged.** An exploration has no recomputable
  brief, so its staleness is unknowable — and unknown is not stale. Docs from
  the `codebase` and `explorer` builders need a human read on a schedule; the
  machine will not raise its hand.

---

## 5. Does it actually help? Run the evals

Everything above checks that the store is *correct*. This checks that it is
*useful*, which is a different question — a perfectly accurate store the model
never consults has changed nothing.

```bash
openstategraph eval ./workflows/chinook-assistant --model ollama:gpt-oss:120b-cloud
```

Run it twice: once as-is, once with the store hidden.

```bash
mv workflows/chinook-assistant/knowledge /tmp/knowledge-parked
openstategraph eval ./workflows/chinook-assistant --model ollama:gpt-oss:120b-cloud
mv /tmp/knowledge-parked workflows/chinook-assistant/knowledge
```

Moving the directory is a real ablation rather than a flag, because seeking is
**ambient**: agents get `knowledge_lookup` whenever the directory is non-empty,
so an empty directory is exactly the "no second brain" condition. (This is also
the fastest way to answer *"is the tool even bound?"* — if the two runs are
identical, look at the binding before you look at the prose.)

Read the difference, not the absolute score. A store that earns its place moves
the cases that depend on domain meaning a schema cannot express — an ambiguous
column, a business rule, a join nobody would guess. If nothing moves, the store
may be accurate and redundant, and the honest response is to write fewer, better
docs rather than more.

See [Evaluation](evaluation.md) for the suite format and thresholds.

---

## 6. Pin it in a test

The checks worth keeping are the mechanical ones. Package tests live in
`workflows/<slug>/tests/` and run under plain `pytest`:

```python
from pathlib import Path

from openstategraph.api.knowledge_curation import list_topics
from openstategraph.knowledge import PackageKnowledge
from openstategraph.schema import normalize_document
import json

PACKAGE = Path(__file__).resolve().parents[1]


def _statuses():
    document = normalize_document(json.loads((PACKAGE / "workflow.json").read_text()))
    return list_topics(PACKAGE, document, PACKAGE.parent)


def test_every_table_has_a_topic():
    names = {entry.name for entry in PackageKnowledge(PACKAGE).topics()}
    assert {"invoice", "invoiceline", "track"} <= names


def test_every_topic_has_an_index_line_a_model_could_choose_from():
    for entry in PackageKnowledge(PACKAGE).topics():
        assert len(entry.hint) > 20, f"{entry.name} has no usable index line"


def test_no_topic_is_stale():
    stale = [entry.name for entry in _statuses() if entry.stale]
    assert not stale, f"the source behind these docs moved: {stale}"
```

The third one is the one to actually keep. It turns "somebody should re-read
the knowledge base" into a failing build the next time a migration lands, which
is the only version of that intention that survives contact with a busy month.

---

## What is deliberately not here

**There is no generated skill.** Distilling a knowledge store into a skill file
was considered and refused: a skill is *rules*, loaded into every prompt of
every agent it is wired to, and knowledge is *reference*, fetched on demand
only on the path taken. Turning one into the other spends the whole prompt
budget the three-tier design exists to save, and creates a second, lossy,
authority-bearing copy that rots the moment a doc is rebuilt. The full argument
is in [`decisions/knowledge-architecture.md`](decisions/knowledge-architecture.md).

If an agent seems not to *know* the store exists, that is a one-sentence fix in
its rules ("look the table up before you query it"), not a generated file.
