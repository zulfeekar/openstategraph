# Web Research Digest

Gallery example 18 of twenty — **search, fetch, report**, and the only example
whose tools leave the machine. Everything else in the twenty either computes,
recalls, or reads a file this repository ships; this one depends on a stranger's
server answering, which is why it is also the only example with a documented
failure shape.

| Node | One line |
| --- | --- |
| `in1` **Research question** | where the question enters |
| `t-search` **Search** | `tool.web-search` — keyless DuckDuckGo, titles and snippets |
| `t-fetch` **Fetch** | `tool.web-fetch` — one page, SSRF-guarded, stripped to 8 000 chars |
| `digest1` **Researcher** | one ReAct agent, many laps over the two tools |
| `grader1` **Did it actually read something** | demands a `Sources:` line and attributable claims |
| `out1` **Digest** | the digest |

One agent looping over two tools — contrast example 20, which spends several
agents to hit several sources at once, and example 16, which chains three
agents because the middle one needs a different tool.

## Deviation from the catalogue, deliberate

Row 18 draws the grader as a plain checkpoint: agent → grader → output, with no
`revise` edge. **A grader wired that way is not a checkpoint; it is a silent
one.** The compiler puts one conditional edge per wired branch, and
`_router_for` falls back to the *first declared destination* when the recorded
decision names no wired branch:

```python
default = next(iter(destinations))
...
chosen = decisions.get(node_id)
return chosen if chosen in destinations else default
```

Strip the `revise` edge from this document and `plan.conditional["grader1"]`
becomes `{"pass": "out1"}` with **no warning** — so a grader that decides
`revise` routes to the output anyway and the run ships a digest its own rubric
rejected. Gallery ticket 31. This example therefore wires the edge, and the
cycle it makes is a research retry: *go and fetch the source you did not
fetch.* `maxAttempts: 2`.

## The rubric forgives a failed fetch, on purpose

Two criteria carry the example:

- every claim must be attributable to a fetched page — *"a digest that would
  read the same if no page had been fetched fails"*;
- **a quoted tool failure passes**, provided no substitute facts ride alongside
  it.

The second is the unobvious half. A rubric that only rewards sources teaches
the model that failing to reach the web is a failing grade, which is exactly
the pressure that produces an invented digest. Honesty has to be a passing
answer or it will not be given.

## Smoke run

```
openstategraph run workflows/web-research-digest \
  "What changed in the most recent Python release?"
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, `attempts: 2` (one revise
lap), `decisions {"grader1": "pass"}`:

> Python 3.14.7, released 8 August 2026, is a maintenance update that includes
> roughly 499 bug-fixes … template-string literals (PEP 750), deferred
> evaluation of annotations (PEP 649/749), `concurrent.interpreters` (PEP 734),
> Zstandard support (PEP 784), a syntax-highlighted REPL, free-threaded mode
> (PEP 779) …
>
> **Sources:** `https://blog.python.org/2026/08/python-3147-31315/`,
> `https://docs.python.org/3/whatsnew/3.14.html`

**Matches.** A point release from the week of the run, two fetched URLs named,
a figure (499) that appears on the fetched page and in no model's weights.

### The failure run, which is the row's real acceptance test

```
openstategraph run workflows/web-research-digest \
  "Read https://no-such-host.invalid/changelog and tell me what changed."
```

Recorded the same day, `attempts: 1`, `decisions {"grader1": "pass"}`:

> I attempted to fetch the page at `https://no-such-host.invalid/changelog`,
> but the host could not be reached (error: "That host is not reachable from
> here"). No content could be retrieved, so I cannot report what changed.
>
> Sources: `https://no-such-host.invalid/changelog` (fetch failed)

The tool's own words, quoted; nothing invented to fill the hole; the grader
passed it because the rubric says an honest failure is an answer. **This is the
catalogue's "a network failure must surface as a readable tool error, never a
silent stub", run.**

The three shapes `web_fetch` reports, all observed:

| Cause | What the agent is handed |
| --- | --- |
| refused host (loopback, private, unresolvable) | `Fetch failed: That host is not reachable from here.` |
| server hangs up | `Fetch failed: Remote end closed connection without response` |
| page loads but strips to nothing | `The page had no readable text.` |

The last one is why an empty success is a bug and not a result: a page that
says nothing and a page that could not be read are different facts, and only
one of them means "try another URL".

## Tests

`tests/` asserts both atoms land on the one agent, that the `revise` edge
exists and where it goes, that the rubric demands sources *and* forgives a
quoted failure, and that a refused host comes back `not ok` with a readable
message and never as an empty success. The refusal test needs no network: the
SSRF guard resolves the name locally and stops before a socket is opened.

## It resists both fixture formats, and the reason is the network

`tests/` asserts the document and the SSRF refusal — both free and both
reproducible. The digest itself is neither.

"What changed in the most recent Python release" has a different correct answer
every few months, so an `evals/*.eval.json` would commit a reference output
with a shelf life, and `refusal_accuracy` in particular becomes noise the
moment a verdict can turn on whether a fetch succeeded — the exact failure
`docs/evaluation.md` records against the old `u04` weather case. A shape
assertion over a run is worse here than elsewhere, because **the network
failure is part of the expectation**: the row's real acceptance test is that a
refused host surfaces as a readable tool error rather than a silent stub, and a
fixture that stubbed the network to make itself deterministic would delete the
thing being tested.

Hence the failure run above is recorded beside the working one. See
`docs/evaluation.md` §"Grading during a run vs grading a dataset".
