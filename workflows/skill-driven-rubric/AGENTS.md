# Skill-driven Rubric

Gallery example 14 of twenty — **rules from one place, read by two nodes**.
The only example where neither the agent's prompt nor the grader's criteria is
typed on the card: both are empty, and both nodes read the same skill.

| Node | One line |
| --- | --- |
| `in1` **Request** | where the request enters |
| `skill1` **Commit message house style** | the rules layer — subject line, body, and what may never appear |
| `write1` **Write the message** | `systemPrompt: ""`, `rulesMode: replace` |
| `grader1` **Check it against the same skill** | `criteria: ""`, `rulesMode: replace`, `maxAttempts: 3` |
| `out1` **Commit message** | renders the message the grader passed |

## What it exists to exercise

**That the skill layer is a layer, not an agent field.** `input.skill.skill`
is an *unlimited* output port; `agent.llm.skill` and `route.grader.skill` are
`maxConnections: 1` inputs. One source, two readers, and the rules the writer
follows are the same bytes the grader checks them against — so the two cannot
drift, which is what happens the moment the criteria are retyped on the grader
card.

`rulesMode: replace` on both is what makes the skill the *only* rules layer.
`SystemPrompt.effective_rules()` keeps the topmost supplied layer and drops the
ones beneath, and the layers bottom-to-top are `default_rules → inline rules →
skill`. The locked preamble and the output contract are untouched by any of
this — they are machinery, they are not editable, and the contract stays last.

## The control run, and what it proves

With the skill wired, the smoke run returned a message obeying rules that
exist nowhere but in `skill1`:

> Fix crash caused by null pointer dereference
>
> The application would abort with a segmentation fault when a function
> attempted to use an uninitialized pointer returned from a library call. The
> update adds a guard that verifies the pointer is non-null before
> dereferencing and returns an error if it is missing. This change prevents
> the abrupt termination and lets the caller handle the condition gracefully.

Imperative subject, 43 characters, no full stop, one blank line, three
sentences of prose, no bullets, no file names, no footer.

A control run on a copy of this document with `skill1` **deleted** — same
question, same model — returned instead:

> **Title:**
> Fix null-pointer dereference causing crash in \<module/component\>
>
> **Body:**
> * Identify and guard against the case where \<variable\> can be `null`…
> …
> Closes: #\<issue-number\> (if applicable)

Bullets, a bold label, placeholders, a footer: four of the skill's explicit
prohibitions, and the grader **passed it**, because unwiring the skill removes
the check at the same moment it removes the rules. That is the point of wiring
one source to both ports, stated from the other direction.

## The word "file"

The catalogue calls this row "rules from a file", and it is worth being exact,
because there are two skill mechanisms and only one of them is drawn here:

| | Where it lives | Who reads it | Wired? |
| --- | --- | --- | --- |
| **This** | `skill1.data.instruction` | whichever `skill` ports it is wired to | yes, visibly |
| Ambient package skills | `skills/*.md` under the package | *every* agent in the package, as context | no — there is no node |

Ambient skills are house style for the whole package and stay *context*; a
wired skill is a **rules** layer for the nodes that asked for it. This example
uses the second, because the first cannot be pointed at two specific nodes and
cannot be seen on the canvas. `docs/decisions/skill-layer.md` has the full
argument, and `openstategraph/skills.py` owns the file format for the times a
skill really is a file.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy skill-driven-rubric
openstategraph run workflows/skill-driven-rubric \
  "Write a commit message for a fix to a null-pointer crash."
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~13s. `decisions` is
`{"grader1": "pass"}` and `attempts` is `1` — the first draft obeyed the skill,
so the `revise` edge was available and unused.

## Tests

`tests/` asserts the shape the recorded expectation rests on: one skill source,
two `skill` edges from it, both readers carrying an empty rules field and
`rulesMode: replace`, and the loop closing on `feedback`. Whether the model
obeys the skill is a model question — the control run above is the evidence,
and a stub answering it would be theatre.
