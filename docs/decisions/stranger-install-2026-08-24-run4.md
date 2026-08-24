# Stranger run 4 — 2026-08-24

Fourth stranger run. Prior three built a workflow; none ran a shipped example
on a fresh install. This run does that: install, discover, copy, run
unmodified, edit through a parent, break deliberately.

## Isolation

```
mkdir -p /tmp/stranger4 && cp /Users/zulfeekar.cheriyampu/dyflow/.env /tmp/stranger4/.env
python3 -m venv /tmp/stranger4/venv
/tmp/stranger4/venv/bin/pip install --no-cache-dir --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ "openstategraph[server,anthropic]==0.3.0rc6"
```

Everything below ran from `/tmp/stranger4`, never the checkout.

## 1. Install

`pip install` completed in **25 seconds** (timed with `date +%s` around the
command; see `INSTALL_SECONDS=25` captured in `/tmp/stranger4/install.log`,
not committed). No network retries, no build-from-source steps.

## 2. Finding the shipped examples

`openstategraph --help` lists an `examples` subcommand directly in the
top-level command list — discoverable without reading any doc. `openstategraph
examples list` prints all 23 shipped examples with a one-line description,
node-shape summary, and mount count in brackets (e.g. `[+2 mounted]`). This is
good discoverability: a new user finds the catalogue from `--help` alone.

`nested-mounts` is present:

```
nested-mounts   composition depth  [+2 mounted]
                Composition depth for its own sake: this document mounts a
                document that mounts a document. One question goes down
                three levels and one answer comes back.
                1 input · 1 workflow · 1 output
```

## 3. Taking a copy

```
openstategraph init . --force
openstategraph examples copy nested-mounts
```

Note: `openstategraph init .` without `--force` refused, because `/tmp/stranger4`
already had 3 files in it (`.env`, `install.log`, `venv/`) — a plain, correct
refusal with the exact next command printed. (This matches ticket 32's
already-filed finding about `init` refusing over files it would not touch; not
re-filed here.)

`examples copy nested-mounts` pulled all three documents transitively:

```
nested-mounts copied: /private/tmp/stranger4/workflows/nested-mounts
  also copied (it is mounted): nested-mounts-mid
  also copied (it is mounted): chained-summarizer
```

Copies arrive with `published: false`, stated plainly by the CLI.

## 4. Running it

`openstategraph validate workflows/nested-mounts` → `VALID`, 3 graph nodes,
entry `in1`, exit `out1`.

`openstategraph graph workflows/nested-mounts --xray` opened **all three
levels**: the top document's `mount_mid` subgraph nests a `mount_inner`
subgraph inside it, and `mount_inner` shows the real `chained-summarizer`
nodes (`summarise1`, `shorten1`) — not one featureless box per mount. This is
the xray behavior CLAUDE.md documents as fixed by `workflow-gallery` 28,
confirmed here from a wheel build rather than the checkout.

Run, unmodified, no edits:

```
openstategraph run workflows/nested-mounts "Explain what a for loop is in programming."
```

Output (5 seconds, timed):

> A for loop is a control structure that repeats a block of code a set number
> of times or iterates over a collection of items to automate repetitive
> tasks.

Coherent, on-topic, and shaped like the composed chain (explain, then
compress to one sentence) actually ran. **The example ran unmodified on a
fresh install.**

**Time from `pip install` to a useful answer: well under 2 minutes** —
25s install + `init --force` + `examples copy` + `validate` + `run`, all near-
instant except the one live model call (~5s).

## 5. Editing through the parent

Followed the override syntax found in the `same-package-twice` example
(`data.overrides.<nodeId>.<field>` on a `workflow.subgraph` node). Edited
`workflows/nested-mounts-mid/workflow.json`'s `mount-inner` node — i.e. edited
the **middle-level parent**, not the leaf package on disk — to add:

```json
"overrides": {
  "shorten1": {
    "systemPrompt": "... end it with the exact tag [OVERRIDE-APPLIED]."
  }
}
```

Re-ran the identical question. Output ended with the literal tag:

> ... to access different elements and avoid writing redundant code.
> [OVERRIDE-APPLIED]

**The edit took effect** — confirmed by an exact string match in the model's
output (a network/content check, not a screenshot), and the leaf package
(`workflows/chained-summarizer/workflow.json`) was never touched — matching
the documented "package on disk is never written" promise.

**What it did not do: say which scope changed.** No CLI output — at
`validate` or at `run` — named the instance or the mount path the override
applied to (e.g. "applying override to nested-mounts-mid → chained-
summarizer#shorten1"). The only confirmation available was inferring it from
the model's own answer. Filed as `launch-readiness/40`.

## 6. Breaking it deliberately

**Unanswerable question**, same document, unmodified:

```
openstategraph run workflows/nested-mounts "What is the current price of Bitcoin right now in USD?"
```

> I don't have access to real-time price data for Bitcoin. My available tools
> are limited to saving and retrieving information from memory within our
> conversation, and they cannot fetch live market prices or connect to the
> internet.
>
> To find the current Bitcoin price in USD, you can check: ...

Plain, honest refusal. **PASS.**

**Mount pointed at a nonexistent package** — edited `nested-mounts-mid`'s
`mount-inner.data.workflow` to `"does-not-exist-package"`:

`validate` output:

```
Workflow 'nested-mounts' loaded with 1 unresolved capability warning(s): Inside
mounted workflow "nested-mounts-mid": The workflow node mounting
"does-not-exist-package" could not load that package — the step produced
nothing.
PROBLEMS FOUND:
- Mount "nested-mounts-mid -> does-not-exist-package" names a package that is
  not in /private/tmp/stranger4/workflows — check the slug, or copy the
  package into this workflows root.
- Inside mounted workflow "nested-mounts-mid": The workflow node mounting
  "does-not-exist-package" could not load that package — the step produced
  nothing.
```

`run` output: exit code 1, `error: Inside mounted workflow "nested-mounts-mid":
... could not load that package — the step produced nothing.`, plus a warning
that the run continued with a stale answer, then: `The workflow finished
without producing an answer.`

Both the missing slug and the produced-nothing consequence are named plainly,
and the run does not silently fabricate an answer. **PASS** — but the
"produced nothing" sentence is printed identically twice (once inline in the
load-warning line, once in the PROBLEMS FOUND list), which reads as a doubled
message rather than two distinct facts. Minor; not separately filed —
folded into `launch-readiness/40`'s write-up as a secondary observation, not
a second ticket, since it is cosmetic duplication rather than a wrong answer.

## Providers

`openstategraph providers` at project root: `anthropic` configured and
default (`claude-haiku-4-5`), `openai` and `ollama` both report credentials
present but need their extras. No fallback occurred — Claude answered on
first try. No `--check` (billable) call made.

## Confirmed by DOM/network vs screenshot

This run used the CLI throughout (no browser/editor session opened), so every
finding here is confirmed by **command output and exit codes** — `validate`
JSON/text, `run` stdout, exit codes — not by a screenshot. Count: 4 findings
confirmed this way (unmodified run's answer content, xray diagram's three
nested `subgraph` blocks, the `[OVERRIDE-APPLIED]` tag round-trip, the bad-
mount error text and exit code).

## Cleanup

`/tmp/stranger4/venv` removed after the run; `/tmp/stranger4/workflows` and
`install.log`/`run1.log` left in place for reference (not committed — outside
the checkout).
