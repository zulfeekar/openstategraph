# A stranger installs it and asks for a workflow — 2026-08-29

The second run of this measurement. The first (`stranger-install-2026-08-23.md`)
reached a published workflow but never reached an answer, so the one number the
exercise exists to produce — **time from `pip install` to a working answer** —
did not exist. This run produces it, twice, and finds one defect that stops the
result from being a clean pass.

Everything below was measured against the locally built `0.3.0rc7` wheel
installed by file path into clean virtualenvs in temporary directories. The
editor was rebuilt (`npm run build`) before the wheel, and both surfaces were
confirmed to load from `site-packages`, not from a checkout's `dist/`.

## 1. The headline number

Two independent clean virtualenvs, `openstategraph[server,ollama]`:

| | run 1 (warm pip cache) | run 2 (`--no-cache-dir`) |
| --- | --- | --- |
| `python3 -m venv` + `pip install` | **10 s** | **16 s** |
| `openstategraph init my_demo` | 0.2 s | 0.2 s |
| first correct answer (`run workflows/starter`) | 3 s | 5 s |
| **`pip install` → first working answer** | **~15 s** | **21 s** |

Constant across both: **46 distributions**, **79 MB** virtualenv, **4.4 MB**
wheel. `openstategraph serve` was ready to answer `/api/health` in **1 s**.

**The number assumes a credential already in hand.** For someone who has
neither an Ollama key nor a Databricks token the total is unbounded — it is a
signup, not a command. What the product does for that person is measured in §4.

## 2. The domain half — Chinook, every question asked twice

`openstategraph examples copy sql-qa` (one command, from a list of 24 worked
examples each carrying a one-sentence description).

| question | truth | run A | run B |
| --- | --- | --- | --- |
| How many customers are there? | 59 | 59 | 59 |
| How many tracks, and which genre has the most? | 3503, Rock | 3503, Rock | 3503, Rock |
| How many customers are from Antarctica? | 0 | `0` | `0` |

`openstategraph eval workflows/sql-qa`, twice: **100.0% overall accuracy** on
5 cases, p50 **6.4 s**, p95 **8.3 s**, **32,302 tokens**, **27.8 s** total.

In the browser, `/chat` answered *"There are 59 customers."* in **2.0 s** and
*"There are 347 albums."* in **1.7 s**, each above a timeline naming what ran.

## 3. The defect that keeps this from being a pass

**`load_workflow(...).ask(...)` returns an empty string on every second call.**

This is the README's headline example and the door a package's own `tests/`
use. The alternation is exact — **5/10 empty on each of two ten-lap trials**,
and identical on `starter`, `chained-summarizer` and `sql-qa`:

```
lap0: 'banana'   lap1: ''   lap2: 'banana'   lap3: ''
```

The failed lap's `RunResult` carries
`warnings=['Node "agent1" failed and produced no result. RuntimeError: Event
loop is closed']` and `attempts=0`. Nothing raises; `str(result)` is `''`.

Three promises are false at once, which is why it is filed as a beta bar
(`launch-readiness/171`):

1. `run_doors.py` lists `CompiledWorkflow.ask` among the four blocking doors
   that run on one loop, and `_WRONG_DOOR` tells a user hitting this exact
   message to *use* `workflow.ask(...)`. The advice points at the broken door.
2. `_WRONG_DOOR` exists to turn this asyncio text into an actionable sentence,
   and does not fire on this path — the raw message is what the user gets.
3. It fails as a blank line rather than an exception.

The diagnosis is a scope error rather than a new bug. `async-first/12` fixed
the *within-run* instance of this — a node body leaves a pooled transport bound
to the loop it ran on, so the second **node** found the loop closed — by moving
the loop's owner from the node call up to the run. The provider **client** is
cached across runs and stayed where it was, so run 2 reuses a transport bound to
run 1's closed loop. Run 3 works because run 2's failure discards it. Scripted
models hold no transport, which is why 6,072 green tests never saw it.

It is invisible to the CLI (one ask per process) and to `serve` (the streaming
door's loop already outlives the run), and hits exactly the surface the pitch
rests on.

## 4. What the product does well, recorded because the run was hunting failures

- **`init` is the strongest thing in the artifact.** It names the default model
  *and* the reason (*"the only provider integration installed"*), prints the
  exact variables, refuses to generate a `.env` with the argument for why
  (*"a generated credential file is a committed one waiting to happen"*), and
  ends with the three commands that follow.
- **The no-credential path is honest at every step.** `providers` separates
  *configured* from *reachable* in as many words and offers `--check` to make
  the difference real. A **missing** credential and a **rejected** one produce
  different sentences: *"The value was read and rejected, so this is a wrong or
  expired credential rather than a missing one."*
- **The `.env` trap recorded in 2026-08-23's run is gone.** `run` reads
  `my_demo/.env` — the file `init` told the user to create — and `providers`
  prints the resolved path with *"(read)"* beside it.
- **The eval card refuses to invent a dollar figure** and prints what it did
  not measure.
- **`/chat` speaks the author's vocabulary** — Question / Analyst / Answer,
  never `in1` / `agent1` / `out1`.

## 5. Corrections made in the same commit

- **`--repeat` made every repetition a follow-up.** `package_asker` gave each
  *case* its own thread id, which predates `--repeat`; two laps of one case
  therefore shared a thread, so lap 2 was the question asked of an agent that
  had just answered it. Each lap now gets its own thread, and lap 1 keeps the
  id it had so a `repeat=1` run is unchanged. This was necessary and **not
  sufficient**: the reported `agreement 20.0%` beside `overall accuracy 100.0%`
  is caused by §3 and survives the fix.
- **An internal ticket id was printed in shipped CLI help.** `eval --repeat`'s
  help text ended `(launch-readiness/126)` — a planning document a wheel
  consumer cannot open, in the one place the tool explains itself to a
  newcomer. Now pinned by a test that walks every parser, so a new subcommand is
  covered the day it is added.
- **The README's wheel figures were stale in both halves** — *"2.7 MB of a
  2.9 MB wheel"* against a measured **110 files, 1.6 MB of a 4.4 MB wheel**.
  That overstated the built editor as 93% of the download when it is a third,
  and it is the evidence in the open package-split decision.

## 6. Also filed

- `172` — the shipped example answers a true zero with the digit `0`. The chat
  timeline *does* say it looked; the answer text does not, so `165` and `166`
  are both invisible on the zero path in the example a new user runs first.
- `173` — Enter does not send in the chat composer, and two questions typed with
  Enter between them merge into one string.

## 7. Verdict

**Through the CLI: yes.** A person who has never seen this project installs it
and gets a correct, checkable answer in about twenty seconds of machine time,
using only the shipped README and `--help`. Several of its error messages are
better than the industry norm.

**Through the library: not yet.** The second question of every session answers
nothing, silently. That is `171`, and it is the whole remainder.
