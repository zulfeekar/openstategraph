# ticket-loop-orchestrator

**Running many ticket-loop sessions without a person in the chair.**
`skills/ticket-loop/` is the shape of *one* session. This is the shape of the
loop *around* it: triage, prioritise, dispatch, verify, repeat — and keep going
until the list is empty or something genuinely needs the owner.

Written from ~40 sessions on 2026-08-23/24, which closed 30+ tickets, found
six product defects, and made every mistake below at least once.

---

## 0 — The rule that outranks the others

**An agent's report is testimony. The filesystem is evidence.**

Three separate sessions reported work they had not done: two explained away a
red gate, one claimed to have delegated to a background task that did not
exist. Each time the tell was identical — a confident summary with no artifact
behind it.

So after **every** session:

```bash
git log --oneline -1        # did it commit?
git status --short          # is the tree clean?
python3 scripts/ticket_ledger.py   # does the ledger agree?
```

That is three commands and it catches everything. Never relay a result you have
not checked.

---

## 1 — Triage: derive the list, never inherit it

Read the newest `.scratch/HANDOFF-<date>.md` and run the ledger. Then derive the
open set yourself — a handoff list is a snapshot and goes stale within hours.

```bash
python3 - <<'PY'
import re,pathlib
S=pathlib.Path('.scratch')
ST=re.compile(r"^(?:Labels:.*?)?Status:\s*(.+?)(?:·|$)",re.M)
CLOSED=('resolved','closed','done','superseded','withdrawn','rejected','moved to','merged into','backlog')
for f in sorted(S.glob('*/tickets/*.md')):
    t=f.read_text(errors='ignore'); m=ST.search(t)
    st=(m.group(1).strip().lower() if m else '(none)')
    if any(w in st for w in CLOSED) and not st.startswith('partially'): continue
    lab=re.search(r"^Labels:\s*(.+)$",t,re.M)
    kind=(re.findall(r"wayfinder:([a-z-]+)",lab.group(1) if lab else '') or ['?'])[0]
    size=(re.search(r"Size:\s*([A-Z]+)",t) or [None,'?'])[1]
    print(f"{f.parent.parent.name}/{f.name.split('-')[0]:<4} {kind:<11} {size:<2} {st[:10]:<10} {t.splitlines()[0].lstrip('# ').strip()[:56]}")
PY
```

**Expect the list to be wrong in your favour.** Of the first thirteen tickets
taken on 2026-08-23, only six needed new code: four were already fixed with
nobody having closed the ticket, one needed proof rather than a fix, one was
bookkeeping. **Never trust a ticket's own framing** — check it against the tree
before acting on what it claims.

---

## 2 — Prioritise: rank by what the defect costs, not by size

In order:

1. **Silent wrongness** — a wrong answer presented as right. Costs trust, and a
   user cannot detect it. Always first.
2. **Blockers** — a ticket several others wait on.
3. **Loud failures** — an error the user sees. Annoying, honest, survivable.
4. **Missing capability** — absent, and known to be absent.
5. **Friction** — slow, ugly, confusing.

A `question`, `grilling`, `design` or `decision` ticket is **not on this list**
— it ends in a judgement and belongs to the owner. Batch those and ask them
together rather than one at a time.

---

## 3 — Dispatch: three gates decide unattended vs. owner

A ticket may run unattended only if **all three** hold:

1. **Reproducible without a person?** A browser reproduction is fine — a
   subagent has browser tools. What is *not* fine is a judgement about what
   "correct" looks like on screen.
2. **Is the decision already made?** If the ticket ends in a choice, it is a
   conversation. Do not pick for the owner.
3. **Is the blast radius contained?** Anything touching the save/draft path,
   the release train, or machinery several tickets depend on gets a person on
   the diff, however headless it looks.

Fails any gate → batch it for the owner with a one-line recommendation.

### Sequential vs. batched

**One session per checkout. Always.** Two sessions collide on `.git/index.lock`,
on the handoff (read-modify-write), and on `session_guard`'s single snapshot.
Overlapping produced a false gate failure and a session that misattributed its
own sibling's edits to a phantom "concurrent session" — three times in one day.

Genuinely parallel work is fine only across **different repositories**.

**Wait for the gate before starting the next.** It costs five minutes and buys
a clean bisect when something breaks.

---

## 4 — Model and effort, by the shape of the work

| Work | Model | Effort |
|---|---|---|
| Mechanical — regenerate, reformat, rename | haiku | low |
| Ordinary ticket — reproduce, TDD, fix | **sonnet** | medium |
| Judgement — "is this a regression or a stale test?" | **opus** | high |
| Exploration under uncertainty — abandon a hypothesis, re-frame | **opus** | high |
| Writing that a stranger will read | opus | high |

**The measured lesson:** a weaker model failed a task four times with the tools
and budget already fixed; a stronger one did it on the first attempt. The gap
was **persistence under a failed hypothesis** — the willingness to drop a frame
and look elsewhere. Cheap models are fine when the facts are in front of them
and wrong when the job is to go find them.

Prefer the cheap model *plus better inputs* over the expensive model — but do
not send a cheap model to explore.

---

## 5 — The brief: what a session needs to not waste an hour

Every dispatch carries these, or you will pay for their absence:

- **The command trap.** Bash auto-backgrounds anything past 120s and nothing
  notifies a subagent. Every long command needs an explicit `timeout: 600000`.
  Roughly ten sessions stalled on this in one day. Say it at the top, in caps.
- **No sub-agents.** A subagent cannot receive a sub-subagent's result. One
  deadlocked exactly this way and then reported work it had not done.
- **What has already been measured**, so it is not re-derived. Name the commits
  that landed since the ticket was written.
- **The non-negotiables that bear on this fix**, quoted — not "read CLAUDE.md".
- **Trailer discipline.** `Ticket: <map>/<n>` only if the ticket is being
  closed. A trailer naming an open ticket is `shipped-but-open` drift, which is
  the exact failure the ledger exists to catch. For a log-only commit, name a
  ticket that is `partially`.
- **A single status word** in a ticket header. `ticket_ledger.py` matches the
  first it sees, so `resolved (partially)` reads as fully closed.
- **The honest outcomes.** "Already fixed, closing with evidence" and "not
  reproducible, no commit" are *correct results*. Say so explicitly, or a
  session will invent work to justify itself.
- **The date.** If it rolled over, today's handoff is a new file.

---

## 6 — Verify, then continue

After the report:

1. Check the three commands from §0.
2. Run `python3 scripts/loop_gate.py` **yourself**. Two independent green gates
   beat one claimed one.
3. **Read what the session says it did not do.** A `partially` header, a
   deferred half, a "noticed but did not fix" — each is a ticket. Under-filing
   is the known failure mode: a consideration left inside a closed ticket is a
   consideration nobody reads.
4. Start the next.

---

## 7 — Keep the loop running

**Anything found on the way becomes a ticket** — `/wayfinder` shape, **local
markdown under `.scratch/<map>/tickets/`, never a GitHub issue.** What you
found and did not do is a ticket, not a footnote.

**Number it safely.** Check the highest ticket *file* **and** the highest
`Ticket: <map>/<n>` trailer in `git log`. "Highest file" is not "highest
number" — a whole ticket exists because of that assumption.

**When the unattended queue empties**, batch every owner-gated question into
one message with recommendations, rather than draining their attention one
decision at a time.

**Explore with `/graphify`, not by reading files.** `graphify explain "X"`,
`graphify path "A" "B"`. This codebase is large enough that orienting by
reading source is a waste of context; `compile/node_runtime.py` alone is over
2,000 lines. `graphify update .` after structural changes.

---

## 8 — The failure modes, so you recognise them fast

| Symptom | Cause | Fix |
|---|---|---|
| Session "waiting for notification" | 120s auto-background | Resume; insist on foreground + explicit timeout |
| Confident report, no artifact | testimony without evidence | §0's three commands |
| Gate red, agent says "unrelated" | usually a real drift row | Read the ledger yourself |
| "A concurrent session changed X" | usually your own other session, or the owner | Check before believing it |
| Ledger drift after a log-only commit | trailer on an open ticket | Retrailer to a `partially` ticket |
| A fix that "works" but nothing changed | stale browser draft, or a server started before the edit | Restart; clear the draft |
| Four screenshots, four findings, two false | photographed before the repaint | DOM assertion or network check, never a photo |

---

## 6.5 Close the ticket before you dispatch the next one

The loop's most common corruption is not a bad session — it is a good session
whose result never got written down. A ticket verified and then left open reads
as unstarted to the next orienting session, and the work gets done twice or,
worse, half-reverted by somebody solving the same symptom differently.

So a ticket is finished only when all of these are true, and you check them
**before** the next dispatch, never in a batch at the end:

- The **ticket header** carries a single status word — `resolved`, or
  `partially` when the shipped work is real but the reported symptom survives.
  Never `resolved (partially)`; the ledger reads the header, and a parenthesis
  reads as done.
- The **ticket body** says what changed and names the commit.
- The **commit** carries `Ticket: <map>/<n>`. The trailer says the work belongs
  to that ticket — never that the ticket is finished. Those are different
  claims and conflating them is what produces shipped-but-open drift.
- **`python3 scripts/ticket_ledger.py`** reports agreement. Run it every time.
  It is two seconds and it is the only thing that catches the header/body/git
  disagreements above.
- **Docs updated** if the change is user-visible, and any **new finding filed**
  as its own ticket rather than mentioned in a report nobody re-reads.
- **Today's handoff** amended — done, next, traps. If the date rolled over
  mid-loop, that is a *new* `.scratch/HANDOFF-<YYYY-MM-DD>.md` carrying the
  live parts forward, not an edit to yesterday's.

Only then pick the next ticket. Deferring this to "the end of the batch" is how
twenty tickets came to read `Status: open` for work that had already shipped
and passed CI — the failure this whole discipline exists to prevent.

## Done means

- Every unattended-eligible ticket taken, each gate-verified twice
- Everything found filed as local markdown, numbered safely
- Owner-gated decisions batched into one message with recommendations
- Today's handoff written — done, next, instrument notes
- The tree clean, the ledger agreeing, nothing pushed
