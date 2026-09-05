# Shapes — which idiom to reach for, and what it costs

The long form of the sheet's *recommend a shape* step. Read it once, at the
end of the interview, before any card is filed.

**The question this page answers is not "what does this workflow do" — it is
"what in this concept is going to multiply?"** Specialists, sources, tenants,
teams, checks, decisions. A concept with one of everything is one agent and
that is the right answer. A concept with fifteen of something has a shape
question, and the wrong answer to it is not wrong on the first one: it is
wrong on the fifteenth, by which time the canvas, the prompt and the test
suite have all grown with the count and nothing can be built, tested, owned or
replaced on its own.

Every idiom below already exists in the installed vocabulary. Nothing here is
a new node type; run `openstategraph nodes` and every type named is in the
list. Where an entry says a shape does not fit, that sentence is the useful
half — a catalogue that only says *when it fits* recommends everything.

---

## The rules, as a table

Read the developer's answers as counts, then read the counts down this table.
**First match wins**, and it picks the *spine* — the thing the canvas is
mostly made of.

| multiplies | shape |
| --- | --- |
| specialists >= 3 | router -> N specialist mounts |
| teams >= 2 | mount, not inline |
| parts >= 2 | supervisor fan-out + report |
| sources >= 3 | one tool family + allowlist |
| otherwise | one agent |

Then read every row of this second table; each one that matches is an
**addition** to the spine, not a rival to it.

| also true | add |
| --- | --- |
| revisions >= 1 | revision loop — a judge that can say what is wrong |
| checks >= 1 | guard gate — a fact the code can check |
| crossings >= 1 | primary + facet — one answer, one grain |
| gaps >= 1 | ask-back — an axis the question must carry |
| tables >= 2 | one tool family + allowlist |
| tenants >= 2 | a domain gate per package, under one generic gate |

The axes, said once so an interview can ask for them by name:
**specialists** (distinct domains, each with its own tables or rules),
**teams** (people who will own a part separately), **parts** (pieces of one
task that merge mechanically), **sources** (stores a question could be
answered from), **tables** (things one connector may read), **revisions**
(whether a second attempt is worth paying for), **checks** (facts code can
settle), **crossings** (questions that name two specialists at once),
**gaps** (axes a question can arrive without), **tenants** (customers or
tiers whose rules differ).

---

## One agent

- **What multiplies:** nothing. One domain, one grain, one set of rules.
- **Fits when** the whole job is a prompt, a tool or two, and an answer.
- **Does not fit when** the prompt has started to carry sections that only
  apply to some inputs. That is a router wearing a prompt's clothing, and it
  is the state every sixty-six-node canvas starts from.
- **Costs:** nothing to build, everything to grow. Each new domain edits the
  one prompt that every other domain also reads, so no part can be changed
  without re-testing all of them.
- **Node types:** `input.text`, `agent.llm`, `output.formatted`.

## Router -> N specialist mounts

- **What multiplies:** specialists. Three or more domains, each with its own
  tables, vocabulary or rules.
- **Fits when** a question belongs to exactly one of them and the choice can
  be made from the question's own words. Each specialist becomes a package —
  its own agent, its own check, its own tests — and the parent canvas is
  question -> which specialist -> that mount -> answer.
- **Does not fit when** there are two domains (the branch is cheaper than the
  packages), or when every question needs all of them (that is a fan-out), or
  when the domains share one table and one rule set (they are one specialist
  with a filter).
- **Costs:** one classification call per question, plus a directory and a test
  suite per specialist. Buys the thing nothing else buys: the sixteenth
  specialist is a new folder, not an edit to the fifteen.
- **Node types:** `resolve.source` or `route.classifier` to choose, then one
  `workflow.subgraph` per specialist. `resolve.vocabulary` first when the
  choice depends on what the question's words mean in this domain.
- **Deterministic first.** `resolve.source` scores the question against a
  catalogue the developer owns and may answer *nothing chosen*; that is the
  point at which `route.classifier` gets to decide. A router that asks the
  model first has no fixture to test.

## Revision loop

- **What multiplies:** attempts. A first answer that is often nearly right.
- **Fits when** a judge can say *what is wrong* in words the producer can act
  on, and a second attempt is worth its tokens.
- **Does not fit when** the judgement is a yes or no about a fact — that is a
  guard gate, and it costs no model call — or when the criteria are only
  clear to a person.
- **Costs:** up to one extra model lap per attempt, and an attempt cap that
  must be set with care. **A cap of 1 sends nothing back:** both judging node
  types treat the first judgement as the last, so "send it back once" is 2.
- **Node types:** `route.grader` with its `revise` branch wired to the
  producing `agent.llm`'s `feedback` port. Two edges, and the loop exists.
- `revise` **cannot fan out.** The compiled plan holds one branch target per
  node, so fifteen drawn edges out of one grader compile to one — silently,
  through a `VALID` verdict. One judge per producer, or one producer.

## Supervisor fan-out + report

- **What multiplies:** parts of a single task, nameable only at run time.
- **Fits when** the parts are genuinely independent and the merge is
  mechanical — a report, a list, a table.
- **Does not fit when** the parts are known in advance (draw them), when one
  part's answer changes another's question (that is a chain), or when merging
  requires judgement (that is another agent, and say so).
- **Costs:** a planning call before any work happens. With one worker role it
  is a planner you pay for and do not use.
- **Node types:** `orchestrate.supervisor`, `orchestrate.worker`,
  `function.format_report`.
- **The report node's inbound port is unbounded for the supervisor's fan-out
  and for nothing else.** Static edges into it compile, validate and run, and
  drop their payloads without a word. If the parts are static, do not join
  them here.

## Guard gate

- **What multiplies:** checks — facts about an answer that code can settle.
- **Fits when** the rule is checkable without a model: a unit beside every
  figure, a stated date window, a cited table that the catalogue actually
  pins.
- **Does not fit when** the property is a matter of taste, or when the check
  can only pass by reading something the answer does not carry.
- **Costs:** a package function and its tests. No tokens. The cheapest
  judgement in the vocabulary, and the one most often skipped.
- **Node types:** `guard.check`, running a function from the package's
  `functions/`. `guard.policy` for the different job of refusing what must not
  leave.
- **Read tolerantly.** A check that matches ASCII hyphens rejects a correct
  date written with a Unicode dash, and the two model laps that follow are
  spent arguing with a right answer.

## Ask-back

- **What multiplies:** gaps — axes a question can arrive without, where any
  value the workflow picks would be a guess presented as a result.
- **Fits when** the missing axis is nameable and its absence is decidable
  before any expensive work: a period, a unit, a tenant.
- **Does not fit when** the workflow could sensibly default. An ask-back the
  user could have skipped is a workflow that argues.
- **Costs:** one classification call, and a branch to an output of its own.
  Today the decision is carried in the classifier's rules — a resolver can
  *say* an axis is uncovered and cannot yet *make* the graph route on it, so
  the sentence is prompt text, and it is pinned by a test rather than
  trusted.
- **Node types:** `resolve.vocabulary` to name the axis, `route.classifier`
  with the missing-axis rule **first**, and a branch reaching its own
  `output.formatted` through a node that produces text.

## Primary + facet

- **What multiplies:** crossings — questions that name two specialists at
  once.
- **Fits when** one answer at one grain is what the reader wants, and the
  second specialist contributes a column rather than a second answer. The
  router names the primary and hands the second along as a facet in the task
  text; the primary joins it only where the catalogue lists the pair as
  joinable.
- **Does not fit when** the two really are two answers. Then it is two runs,
  or a fan-out, and pretending otherwise produces one number at the wrong
  grain.
- **Costs:** a joinability declaration the developer maintains. Buys the
  absence of a second router pass.
- **Node types:** none of its own — it is a property of the same
  `resolve.source` / `route.classifier` decision.

## One tool family + allowlist

- **What multiplies:** sources and tables. Many things one connector may read.
- **Fits when** the many are the same kind of thing behind one credential:
  one warehouse, forty-two tables.
- **Does not fit when** the sources need different credentials or different
  dialects. That is two atoms, and the vocabulary already has more than one
  query atom for exactly this reason.
- **Costs:** an allowlist file the connector refuses to read outside, and a
  test asserting the pinned names are **equal** to the catalogue's — a refusal
  printing a shorter list must be red.
- **Node types:** `tool.sql-query` or `tool.mssql-query`, bound onto every
  agent that needs it. A tool binds *into* an agent rather than being a graph
  node, so `openstategraph graph` will not show it; `openstategraph validate`
  is the surface that does.

## Mount, not inline

- **What multiplies:** teams, and reuse.
- **Fits when** a part will be reused, must be isolated (task in, answer out,
  no shared state), or will be owned by somebody else. A mount is a package
  with its own document, its own tests and its own rules file.
- **Does not fit when** the part is three nodes used once. A package has a
  directory, a test suite and an upgrade path, and none of that is free.
- **Costs:** a folder per part, and a name that is frozen once minted. Buys
  the thing the whole page is about: the multiplied part stops living on the
  parent's canvas.
- **Node types:** `workflow.subgraph`.
- **A mount is by reference.** Change the package and every instance changes.
  Starting from a template is a copy, and the link is severed at that moment.

## One generic gate in the parent, one domain gate per package

- **What multiplies:** tenants and specialists together — rules that differ by
  domain, over a floor that does not.
- **Fits when** some checks are true of every answer (a unit, a window, a
  cited source) and others are true only of one domain's.
- **Does not fit when** there is only one domain: two gates then check the
  same thing twice and disagree eventually.
- **Costs:** two places to look when a check fails. Buys a floor no package
  can drop below and a ceiling each package sets for itself.
- **Node types:** `guard.check` in the parent; `guard.check` plus
  `route.grader` inside each package.

---

## The worked example — sixty-six nodes, then fifteen mounts

Written from a real transcript, not invented.

A developer brought a concept with fifteen resolvers over one data warehouse:
each resolver its own tables, its own grain, its own vocabulary, its own
rules about what an honest figure looks like. The interview asked its eight
dimensions, every answer was concrete, six cards were filed and the workflow
was built. It validated. It ran. It answered a real question with a real
figure from a real table.

It was also **sixty-six nodes on one canvas** — fifteen agents, fifteen
guards, fifteen graders, fifteen outputs, sixteen exits — generated by a
script because no one could draw it. Every one of those nodes was correct.
The shape was not.

Read against the tables above, the same interview answers say so in one pass:

| axis | the answer | rule |
| --- | --- | --- |
| specialists | 15 | `specialists >= 3` -> **router -> N specialist mounts** |
| tables | 42 behind one connector | one tool family + allowlist |
| crossings | a question naming a second specialist | primary + facet |
| checks | unit, window, cited table | guard gate |
| revisions | a rubric that can say what is wrong | revision loop |
| gaps | a question with no period | ask-back |
| sources | 1 warehouse | *(no second connector)* |

So: **fifteen packages behind one router**, each mounted, each with its own
agent, its own domain check, its own rubric and its own tests; one generic
gate in the parent; a crossing answered as a primary with a facet; a
specialist that declines retried once and then asked about. The parent canvas
is question -> axes -> which specialist -> fifteen mounts -> answer, and the
sixteenth specialist is a new folder.

Nothing in that paragraph is a node type the platform lacked. The idioms were
all there; what was missing was the sentence saying which one this concept
needed, said **before** the first card was filed rather than in a ten-minute
conversation after the build.

Two things that shape would have avoided, both paid for in full:

- Fifteen drawn `revise` edges out of one grader compiled to **one**, through
  a `VALID` verdict, because a plan holds one target per branch. One judge per
  package cannot have that defect.
- Fifteen static edges into one report node compiled, ran, and published the
  join's own empty message as the customer's answer. A mount returns its
  answer to its own tail; there is nothing to join.
