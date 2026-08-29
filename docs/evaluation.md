# Evaluation

How a workflow is measured here, why the metric is the one the text-to-SQL
field already agreed on, how to add a case, and how to read a regression.

The harness is `openstategraph.evaluation` (Tier 2, provisional) behind one
command:

```bash
openstategraph eval ./workflows/chinook-assistant
```

## Grading during a run vs grading a dataset

Two things in this system judge an answer, they share almost all their
machinery, and confusing them is the most common way to misread everything
below. A `route.grader` node judges one candidate mid-run. `openstategraph
eval` judges a whole dataset offline. Same judge — **different consumer,
different clock**:

> A grader's verdict is an **edge**. `pass` or `revise`, consumed by the graph,
> acted on in milliseconds, spent immediately.
>
> An eval's verdict is a **destination**. A scorecard, consumed by a human or a
> CI gate, kept and diffed against the next one.

The code says it more precisely than prose can. `BaseGrader.grade()` runs its
deterministic checks first and only then asks a model
(`backend/openstategraph/abc/grader.py`); `runner._grade()` **judges** without
a model at all — recover the SQL, execute the gold query, compare denotations
(`backend/openstategraph/evaluation/runner.py`). It does run the workflow first,
so a model is called in the course of the case; what is model-free is the
verdict. Both end in a fixed verdict vocabulary. They are the same function at two time scales.

### Which half of the field we actually hold

The industry vocabulary splits evaluators twice: **offline** (pointed at a
dataset, reference outputs available) vs **online** (pointed at live runs, no
references), and **LLM-judge** vs **deterministic code**. We occupy one
diagonal of that square, on purpose:

| | Deterministic code | LLM judge |
| --- | --- | --- |
| **Offline** — a committed dataset | ✅ `openstategraph eval` — execution accuracy | ❌ rejected, with a named trigger: [Should we add an LLM judge?](#should-we-add-an-llm-judge) |
| **Online** — a live run | ❌ no trace store, so nothing to point one at | ✅ `route.grader`, `RubricMiddleware` — and it *steers* the run rather than observing it |

Both blanks are decisions rather than oversights, and they are not the same
decision. The offline judge is refused below. The online *monitor* is missing
because we have no tracing project to aim one at. Everything the eval
vocabulary offers that we lack — online evaluation, backtesting, experiment
comparison — is downstream of that one absent capability, not of an eval
feature we skipped.

**Per-run token cost is no longer on that list** (`workflow-gallery` 35). It
was, and the reason given was the tracer; that reason was wrong.
`langchain-core` aggregates `AIMessage.usage_metadata` per model through
`get_usage_metadata_callback`, in-process and with no account, so `ask()` now
returns it on `RunResult.usage` and the scorecard's `cost` block carries the
dataset's measured tokens per model. What is still absent is **money**: `usd`
stays `null` because prices are per-account, change without notice, and live
in no file this project owns — a caller with a price table multiplies
`cost["tokens"]` themselves. An unmetered provider leaves `total_tokens`
**`null`**, never `0`; unknown is not free.

The in-graph judge has no equivalent on the other side of that table, and the
difference is worth naming: a hosted judge observes a run from outside and
writes a score; ours sits on an edge and changes where the run goes next.

### The third thing, which grades nothing

A package's `tests/` directory is neither of the above and is easy to mistake
for the first. It asserts the **document and its compiled plan** — the wiring,
the ports, the model pin, a warning-free assembly — via
`openstategraph.package_testing`. It calls no model, costs nothing, and runs on
every `pytest`.

| | asserts | costs | when |
| --- | --- | --- | --- |
| `route.grader` | a candidate answer, in-graph | a model call | every run |
| `openstategraph eval` | a dataset of known answers | a model call per case | deliberately |
| `<package>/tests/` | the document and its plan | nothing | every `pytest` |

That split is why all but one of the gallery packages carry a `tests/`
directory and only `sql-qa` carries an `evals/` directory: a shape is an
**assertion** (binary, no reference corpus needed), while an answer's quality
is a **metric** (fuzzy, useful in relative terms). The one without is
`nested-mounts-mid`, a nested child rather than an example in its own right.

Three packages cannot assert an *answer* and say so in their own `AGENTS.md` —
`approval-in-the-loop` (the answer does not exist until a person supplies one),
`youtube-trend-digest` (the correct answer changes daily) and
`web-research-digest` (the network failure *is* the expectation). Their
`tests/` assert the document and its plan like everyone else's; what stands in
for the answer is a recorded smoke run.

**Eval is not a third axis.** It is the same judgement machinery pointed at a
dataset instead of at a run, so there is no eval node on the canvas and there
should not be one. CLAUDE.md's lexicon carries the one-line version.

## The metric: execution accuracy

**Execution accuracy (EX)** runs the generated SQL and the gold SQL against the
same database and compares the **result sets**. It is what
[Spider](https://arxiv.org/abs/1809.08887) reports through its official
test-suite evaluator (Zhong, Yu and Klein, *Semantic Evaluation for Text-to-SQL
with Distilled Test Suites*, EMNLP 2020 —
[`taoyds/test-suite-sql-eval`](https://github.com/taoyds/test-suite-sql-eval))
and what [BIRD](https://bird-bench.github.io/) reports as its headline number.

It exists because the obvious alternative — comparing the SQL *strings* —
scores a correct query wrong whenever the model spells a join differently,
names a column differently, or reaches the same rows through a `GROUP BY` where
the gold used a subquery. `COUNT(*)` and `COUNT(id)` are the same answer.

`openstategraph/evaluation/denotation.py` is a faithful port of upstream's
`result_eq`, and four of its decisions come from there verbatim:

| Decision | Why |
| --- | --- |
| **Bag semantics, not set semantics** | two identical rows are two rows; `set()` cannot tell a query that lost a duplicate from one that did not |
| **Row order matters only when the gold query has `ORDER BY`** | upstream: `order_matters = 'order by' in g_str.lower()`. A question that did not ask for a sort must not be graded on one |
| **Column order does not matter** | the evaluator searches column permutations, so `SELECT name, revenue` and `SELECT revenue, name` agree |
| **Rows are canonicalised with `str(x) + str(type(x))`** | which is also why a `NULL` in a result set is a comparison rather than the `TypeError` that `sorted(row)` over mixed `None`/`str` raises |

**Two deliberate deviations, both toward a reproducible number:**

1. **Float tolerance.** Upstream compares floats exactly. `SUM(UnitPrice *
   Quantity)` and an equivalent formulation differ in the last bits of a
   double; scoring that wrong measures IEEE 754, not the model. Values are
   rounded to six significant digits before comparison.
2. **Deterministic permutation pruning.** Upstream samples 20 *random* rows to
   shrink the column-permutation search. The pruning never changes the answer,
   only the work, so here it reads a fixed prefix instead. A scorecard that is
   not reproducible is not evidence.

### The other numbers on the scorecard

| Field | Meaning |
| --- | --- |
| `execution_accuracy` | the metric above, over the answerable cases |
| `exact_set_match` | BIRD's blunter `set(pred) == set(gold)`: no column permutation, no float tolerance. Reported as the stricter lower bound — the gap between the two is the share of items that are right for a reason a naive comparison would miss. **This is not Spider's string-level Exact Set Match**, which we deliberately do not implement: it punishes correct-but-different SQL, which is the whole reason EX exists |
| `refusal_accuracy` | of the deliberately unanswerable questions, the share the system declined instead of inventing |
| `overall_accuracy` | every case, answerable or not. **This is what `--threshold` gates on** — gating on execution accuracy alone would let a system score well by inventing an answer to every question it cannot know |
| `sql_recovery_rate` | how often a query could be recovered from the answer at all. A system that is right but silent about its query is unverifiable, and that is a finding, not a rounding error |
| `attempts_total`, `retried_items` | model-node invocations across the graded runs — how hard the workflow is working for the score. Not a lap count: a cycle holding two agents spends two per lap (`workflow-gallery` 21) |
| `latency_p50`, `latency_p95` | nearest-rank percentiles, defined explicitly so two runs agree |
| `cost` | usually `null` with the reason: `RunResult` carries no token usage. Attach LangSmith (`LANGSMITH_TRACING=true`) for real per-run token and dollar accounting |

### What it does not measure

Printed on every scorecard, not buried here:

- answer phrasing, tone, and whether the explanation is right for the right reasons
- conversational behaviour across turns (every case runs on its own thread)
- safety, prompt injection, data exfiltration
- cost, unless the run reports token usage
- SQL efficiency — BIRD's Valid Efficiency Score is not computed

An LLM judge is the obvious way to reach the first of those. It is not part of
the harness, and the reasoning is in [Should we add an LLM
judge?](#should-we-add-an-llm-judge) below.

## The dataset

One JSON file per package, discovered by convention at
`<package>/evals/<name>.eval.json`. The shipped one is
`workflows/chinook-assistant/evals/chinook.eval.json`: **36 cases — 31
answerable (10 easy, 13 medium, 8 hard) and 5 unanswerable.**

```json
{
  "id": "h01",
  "question": "Which genre earns the most revenue? Name the genre and the figure.",
  "difficulty": "hard",
  "expects": "answer",
  "gold_sql": "SELECT g.Name AS Genre, ROUND(SUM(il.UnitPrice * il.Quantity), 2) AS Revenue FROM ...",
  "order_matters": false,
  "notes": "The flagship question: three tables, an aggregate over a computed column.",
  "expected": { "columns": ["Genre", "Revenue"], "rows": [["Rock", 826.65]], "row_count": 1 }
}
```

Three properties are deliberate.

**The expected rows are committed, and generated rather than written.** They
come from running the gold SQL against the committed database. That is what
makes a regression visible *in a diff* rather than as a number that quietly
moved: change the database or a gold query, and the pull request shows which
rows changed. `backend/tests/test_eval_dataset.py` fails the default test run
if the file and the database drift apart, and the runner re-executes every gold
query anyway and warns when the two disagree — a stale file can never silently
become the truth.

**Unanswerable questions are cases.** Chinook has no customer birth dates, no
streaming plays and no cost of goods, so a system that answers "what is the
average age of our customers?" is inventing. Those five cases are graded on
what the system did *not* do: `expects: "refusal"` is correct exactly when no
query was recovered and no `forbidden_patterns` regex matches the answer. A
harness that only scores answerable questions rewards guessing.

**"Unanswerable" is a property of the workflow, not of the database** — a
distinction ticket 15 learned by tripping over it. `u04` used to ask for the
weather in Berlin, on the reasoning that it is outside Chinook entirely. Then
ticket 10 collapsed the two Chinook packages into one document with
`web_search` and `web_fetch` wired to a `b-web` branch, and the question
became answerable: the workflow fetches `wttr.in`, cites it, and is right. Its
`forbidden_patterns` (`sunny`, a degree sign) then scored that correct,
sourced, tool-grounded answer as `invented_answer` — and scored it
`refused_correctly` on the runs where the fetch happened to fail. A refusal
case whose verdict tracks network reachability rather than honesty is worse
than a missing case: it puts noise in the one number that means "it lied".
So when a document gains a branch, re-read the refusal set against **every**
branch it now has.

**Ordering is a property of the question.** `order_matters` follows Spider's
derivation by default and is overridden per case where a sort is incidental —
`ORDER BY … LIMIT 1` sorts in order to *pick*, not in order to *present*, and
`m04` sets it `false` because two of its five customers are tied at 45.62, so
the order between them is arbitrary and only membership is graded.

### Adding a case

1. Add the object to `cases` — `id`, `question`, `difficulty`, and either
   `gold_sql` or `"expects": "refusal"`. Leave `expected` out.
2. Generate the expectation and read what it produced:

   ```bash
   python3 scripts/refresh_eval_expectations.py \
     workflows/chinook-assistant/evals/chinook.eval.json
   ```

3. `PYTHONPATH=backend python3 -m pytest backend/tests/test_eval_dataset.py -q`.

Three rules of thumb. Two are enforced by that test file: keep an expectation
to **30 rows or fewer** (ask for a top-N instead of everything, or it stops
being reviewable in a diff), and write `notes` on every unanswerable case
saying *why* the database cannot answer it. The third is **advice, not a
gate** — avoid a `LIMIT n` whose cut falls in the middle of a tie, or a correct
query can return a different, equally correct set. Nothing detects that; the
committed `m04` case is the worked example of it, and it carries
`order_matters: false` for exactly this reason.

## Running it

```bash
# the real thing: calls a model, costs money, takes minutes
openstategraph eval ./workflows/chinook-assistant --model ollama:gpt-oss:120b-cloud

# a subset while iterating
openstategraph eval ./workflows/chinook-assistant --limit 5

# machine-readable, for a dashboard or a diff
openstategraph eval ./workflows/chinook-assistant --json > scorecard.json

# a CI gate: exit 1 below the bar
openstategraph eval ./workflows/chinook-assistant --threshold 0.8
```

| Flag | |
| --- | --- |
| `--dataset PATH` | a specific `*.eval.json`; the default is the one under `<package>/evals` |
| `--limit N` | grade only the first N cases, in file order |
| `--model` | any model string `load_workflow` accepts. Omit for the package's own |
| `--threshold F` | exit **1** when `overall_accuracy` is below `F` (0..1). Default 0: report, do not gate |
| `--repeat N` | ask each case N times and report whether the answers **agreed**. Reported, never gated |
| `--json` | the whole scorecard as JSON instead of the table |

Per-case progress goes to **stderr**, so `eval --json > card.json` still pipes
cleanly and a thirty-question run is not thirty minutes of silence.

### Asking the same question twice — `--repeat`

`launch-readiness/126`. A question asked three times against an unchanged
warehouse answered correctly, then refused with an invented country set, then
refused correctly — **each delivered with identical confidence**, so a user who
asks once cannot know which of the three they got. A second question split
2 / 0 / 0 the same way. The defect was not the wrong answer; it was that the
same question did not produce the same answer, and nothing noticed.

Both were diagnosed to named causes and fixed — a concurrent-search merge keyed
on arrival, and a filter silently not applied — and eight runs afterwards
agreed. What was still missing is the **instrument**: nothing measured
stability, so the next regression of that shape would be as invisible as the
last.

```bash
openstategraph eval ./workflows/chinook-assistant --repeat 3
```

```
agreement               94.4%   (asked 3x each; 2 case(s) not comparable). Reported, not gated.
```

**It reports a rate and gates nothing.** `--threshold` still reads
`overall_accuracy` alone, and a run that disagreed with itself still exits 0.
That is deliberate and it is the ticket's own reasoning: a run is a full model
turn, so this can never sit on a commit, and *a flaky check that is allowed to
stay red teaches everyone to ignore it*. A tracked rate is honest; a green test
that only passes when the coin lands right is not.

**What agreement means here.** Two axes, kept apart, because two answers can be
equivalent in different prose:

| Axis | What it compares |
| --- | --- |
| `verdicts_agree` | did every repetition grade the same way — coarse, always available |
| `results_agree` | did every repetition's statement return the same **rows**, by the same `result_eq` execution accuracy uses |
| `figures_agree` | did every repetition's answer assert the same **quantities** — reaches no database |

`results_agree` is the strong one and the reason a literal-statement pin was
refused: what survived the fixes was *a column alias and where the `DISTINCT`
sits*, and a text pin would be red on a correct run. Rows are immune to that
and are not immune to a genuinely different query.

`figures_agree` is the one that reaches nothing (`launch-readiness/170`). It
reads the quantities out of each answer with `grounded_numbers.quantities_in`
— the same rule that separates a count from a version number or a list marker
— and compares the sets, so `6,119` and `6119` are one figure. It needs no
committed database, no network and no model, which is exactly what a question
answered against a warehouse can offer.

**Rows decide wherever rows exist.** `figures_agree` is reported on every case
and counts toward the rate only where `results_agree` is `null`, so a lap that
wraps the same rows in a sentence carrying one extra date is never a second
answer. It speaks only for the case the strong axis cannot reach at all.

Both are **`null`**, never `false`, when fewer than two repetitions offered
that axis anything to compare. *We could not tell* and *they disagreed* are
different findings, and `unmeasurable` counts the cases where **no** axis could
tell.

**It compares what ran, not what the answer said ran.** `AskOutcome.statements`
comes from `RunResult.statements` (`one-chinook-honest/30`), so two runs
quoting the same query while executing different ones are correctly reported as
a disagreement. `ItemVerdict.sql` and `sql_recovery_rate` deliberately do not
move: they measure whether the system *stated* its query, which is a different
fact and keeps its name.

**Cost.** `--repeat 3` over 36 cases is 108 model turns. The first repetition
is the one that scores, so every other number on the card means exactly what it
meant before and a `--repeat 1` card is unchanged.

**What it cannot cover yet, and what turned out not to be the obstacle.** The
two cases that motivated the ticket are still not in any `evals/` directory:
this harness executes gold SQL against a **committed SQLite file**
(`denotation.connect_readonly`), an answerable case is required to carry
`gold_sql`, and `EvalDataset.database` is required too. Both of those questions
are answered against Databricks.

`launch-readiness/170` asked whether the answer is a second denotation engine,
since agreement compares runs to each other and needs no ground truth. **It is
not**, and neither is simply permitting a gold-less case. Reading the harness,
both axes it compared reached the database — `verdicts_agree` compares grades,
which come from executing gold, and `results_agree` re-executes each lap's own
statement. A gold-less warehouse case would therefore have reported verdicts
that agree because every lap was graded the same coarse way, beside
`results_agree: null`: three different answers published as agreement, which is
worse than no measurement.

What was missing was a comparison that reaches nothing, and `126`'s own symptom
says which one — *one question, three answers* means three different **figures**.
That axis is `figures_agree` above, and it is built. What remains for these two
questions is the dataset format rather than the measurement: a third expectation
that grades on agreement alone, and an `EvalDataset` whose `database` may be
absent. Filed on `170`.

### It is not in the normal CI job, on purpose

A live eval costs money on every push and flakes when a provider hiccups, and a
gate that flakes is a gate people learn to re-run. So the default job tests the
**harness** — `backend/tests/test_evaluation.py`,
`backend/tests/test_eval_cli.py` and `backend/tests/test_eval_dataset.py` run
offline in under a second, driving the real `load_workflow` path with a
scripted model, real SQL execution and the real scorecard.

Run the live eval deliberately: on a schedule, before a release, or on a pull
request that changes prompts or node semantics — with `--threshold` set to the
number you are willing to defend.

## Reading a regression

The scorecard's verdict vocabulary is fixed, and each verdict points at a
different thing to fix:

| Verdict | What actually happened |
| --- | --- |
| `correct` | result sets agree |
| `wrong_result` | the SQL ran and returned something else — a schema-understanding or join problem |
| `sql_error` | a query was stated but does not execute — the retry loop gave up, or the recovered text was truncated |
| `no_sql` | an answer with no query behind it. Either the model answered from parametric knowledge, or it stopped stating its SQL — check which, they need opposite fixes |
| `refused_correctly` | an unanswerable question, declined |
| `should_have_refused` | it queried the database for something the database does not hold |
| `invented_answer` | it asserted a claim matching the case's `forbidden_patterns` |
| `dataset_error` | **our** bug: the gold query failed. Fix the dataset |
| `run_error` | the workflow raised — a provider outage, a compile failure. Not a model quality signal |

Two scorecards diff cleanly: `to_json()` is deterministic, in dataset order,
with rates rounded to four places and no timestamp. When a number moves, diff
the `items` array to find which cases changed verdict before arguing about the
average.

## Should we add an LLM judge?

Not yet, and the decision is recorded rather than deferred. Execution accuracy
grades the *denotation* of a query, which is the part that can be wrong without
anyone noticing. The parts a judge would add — phrasing, whether the
explanation matches the query, how gracefully a refusal reads — are the parts a
human reviewer can spot in one pass over the answers, and none of them is what
this workflow gets wrong. A judge also reintroduces exactly what this harness
was built to avoid: a score whose ground truth is another model's opinion, that
moves when the judge's model is upgraded, and that cannot be reproduced from
the repository alone.

The trigger for revisiting: if `refusal_accuracy` and `execution_accuracy` are
both high while readers still report the answers as unhelpful, the gap is
phrasing, and a judge — scoped to phrasing only, never to correctness, with its
prompt and model version committed — becomes worth its cost.

## Where the code is

| | |
| --- | --- |
| `backend/openstategraph/evaluation/denotation.py` | the Spider/BIRD comparison and read-only SQL execution |
| `backend/openstategraph/evaluation/dataset.py` | the golden file format, validation, expectation refresh |
| `backend/openstategraph/evaluation/recovery.py` | recovering the SQL from an answer written for a human |
| `backend/openstategraph/evaluation/scoring.py` | verdicts, the scorecard, and what it does not claim |
| `backend/openstategraph/evaluation/runner.py` | the loop, over `load_workflow` — no second execution path |
| `backend/openstategraph/package_testing.py` | the third thing above: what a package's `tests/` asserts about its document, shared by all of them |
| `scripts/refresh_eval_expectations.py` | regenerate the committed rows |
