# The gallery was asked a question, and only one package could not answer

**Status: measured 2026-08-29/30.** Resolves `launch-readiness/188` and settles
`launch-readiness/185`, whose real question was not *how do I fix chinook* but
**is this a core defect or one package's?**

The instrument is committed, like every other measurement on this map:
`scripts/run_the_gallery.py`, with its questions beside it in
`scripts/gallery_questions.json`. It is a **hand-run driver, not a CI job** —
CI cannot call a model — and the precedent is `scripts/run_stress_workload.py`,
`scripts/measure_setup_path.py` and `scripts/measure_turn.py`, committed for
their own stated reason: *so the next person re-measures instead of re-argues*.

---

## The gap it closes

```
24 example packages in backend/openstategraph/examples/
22 have tests/     assert the document and the wiring, "neither of them needing a model"
 1 has evals/      sql-qa only
```

Those tests are the right thing to assert in CI. What they leave uncovered is
the live-run layer, and that is exactly where `185` lives. **Before this sweep,
twenty-three of the twenty-four examples had never been asked a question.**

## Why the questions are a committed list

The first two candidates both failed, and the failures are the argument:

- **One generic prompt** ("what can you do?") reaches every package's first
  node and tests almost nothing past it. A router sorts it, a loop grades it,
  and neither exercises the mechanism the example exists to demonstrate. Worse,
  it makes the result unreadable — a package refusing a question it was never
  meant to be asked looks exactly like a package that is broken.
- **The package's own `input.text` default.** The better idea, and it does not
  carry: every one of the twenty-four examples ships `in1` with an **empty**
  prompt, deliberately, because the editor's Examples shelf wants a blank
  field.

Where a committed dataset exists it is used rather than duplicated: `sql-qa`'s
question is case `s04` from its own `evals/`, so the sweep and the eval ask the
same thing. One dataset cannot cover twenty-four packages, which is why the
rest are written down as a set that can be reviewed as a set.

Each entry also records what the sweep should **see**. That is what keeps
`budget-exhaustion` — whose rubric cannot be satisfied by construction — out of
the defect column, and it is the field the sweep corrected on its first run:
the expectation was written as `refused` and the package answered. It was
right to. `compile/nodes/grader.py` swaps in its refusal sentence only when the
last candidate is **empty**, and that drafter always writes its seven words, so
the forced pass has something to hand on. The exit is the attempt counter and
the outcome is still an answer.

## Run it more than once

The default is two laps and the default is load-bearing. The most valuable
finding of 2026-08-27 was not a latency, it was *"three runs, three different
answers"*. A single lap of this sweep can report that a package works when
what it means is that it worked once — and `chinook-assistant-simple` is the
worked example: **answered on lap one, refused on lap two, same question.**

## The result, before the fix

29 entries, 2 laps each, `ollama:gpt-oss:120b-cloud`, on `d675aea`:

```
26 of 29 met their expectation
 1 entry disagreed between its own two laps
 3 did not:
   budget-exhaustion         — the expectation was wrong, not the package (above)
   chinook-assistant         — refused, refused    both laps silent:agent-sql
   chinook-assistant-simple  — answered, refused   one lap silent:agent-sql
```

Every other agent in the gallery answered, twice, including `sql-qa`, which
holds the *same three SQL tools over the same database*.

**So it is one package's, and the mechanism is core.** Those are not in
tension, and the distinction is the whole finding: nothing is wrong with
`chinook-assistant`'s document, and the failure mode it hits belongs to the
agent node. It is the only package that hits it because it is the only one
whose agent runs a long multi-tool loop over large tool results — a schema dump
per table, three thousand prompt tokens by the third call. `sql-qa` asks one
aggregation and finishes in seven seconds; `chinook-assistant` was asked to
combine two.

## What the failure actually is

`185` said to establish this before touching anything, because "the message is
empty" and "the message was lost after the agent" are two defects with two
owners. Captured off a live reproduction of the owner's own question:

```json
{"type": "ai", "content": "", "tool_calls": [],
 "response_metadata": {"done_reason": "stop", "eval_count": 92,
                       "model": "gpt-oss:120b-cloud"}}
```

The model generated ninety-two tokens and published none of them as content.
`_final_text` returned `""` and was **right** to — there is nothing there, and
`production-ready/96` had already settled the same fact off the raw Ollama
wire. Nothing is lost after the agent.

What was missing is that nothing tried again. The grader's revise edge sent
`The answer is empty.` back to the agent, which re-ran the whole tool sequence
and ended silent again, three times — because a silent turn is not a content
problem and no feedback about the content addresses it. `185`'s own note that
the three laps got *shorter* is the same observation from the other end.

The recovery is one more ask, with the tool results already in the conversation
and no tools bound. On the reproduction it recovered **four of five** silent
turns. `openstategraph/compile/silent_turn.py` is the whole of it.

## The result, after the fix

The same sweep, same shape, same model, on the fix:

```
29 of 29 met their expectation
 0 entries disagreed between their own two laps
```

`chinook-assistant` answered both laps of the owner's own compound question —
43.3s and 25.2s, three attempts and two — and `chinook-assistant-simple`
answered both in 11.3s each, against one refusal before.

Driven harder, because two laps of a thing that fails one time in three proves
little. `chinook-assistant`, the compound question, eight laps:

```
before   0 answered / 2 laps      (2 refusals)
after    6 answered / 8 laps      (0 refusals; 2 runs lost to a provider 500,
                                   each reporting the provider's own message)
```

`chinook-assistant-simple`, four laps: **4 answered, 4 of 4**, against one of
two before.

The two remaining losses are `ollama._types.ResponseError: Internal Server
Error (status code: 500)` exhausting the node's three retries, reported as
`Node "agent-sql" failed and produced no result` with the provider's reference
id. That is a provider outage described accurately, which is the outcome this
project wants from one.

## Does the model matter? Yes, and it decides how to read all of the above

`185` asks, because `CLAUDE.md`'s standing rule is that a weak model turns a
wiring bug and a capability gap into the same symptom. The same package, the
same compound question, three laps each:

| Model | Result |
| --- | --- |
| `ollama:gpt-oss:120b-cloud` | silent turns; 2 of 2 refused before the fix |
| `openai:gpt-4.1-mini` | **3 of 3 answered**, no silence, no node retries |

`gpt-oss` is a reasoning model in the harmony format, and the silent turn is a
turn it spent entirely on the analysis channel. `langchain_ollama` drops that
channel unless `reasoning=True` is passed — verified here — so the tokens have
nowhere to go and `content` arrives empty. **That is not a reason to publish
the reasoning channel as the answer**: `CLAUDE.md` and `_final_text` both
forbid it, and a model's private working is not prose for a person. It is the
reason the recovery is a second ask rather than a wider parse.

The consequence for anyone reading a gallery result: this is a property of the
**default** model, which is also the model `chinook-assistant`'s own document
names. So it is ours to survive whether or not it is ours to cause.

## What the sweep is not

Not an eval. `docs/evaluation.md` §"Grading during a run vs grading a dataset"
holds the distinction and it applies here: an eval grades a **dataset** with
known answers and produces a scorecard. This sweep asks one question per
package and reports what came back — answered, refused, paused, empty, errored,
with attempts, routing decisions and which nodes published nothing. It is the
smoke test the gallery did not have, not a replacement for the one dataset that
exists.

Not a CI gate either, and the reason is the same one every hand-run driver in
`scripts/` carries: it spends real money on a real provider, and two of its
twenty-nine entries depend on a stranger's server answering.
