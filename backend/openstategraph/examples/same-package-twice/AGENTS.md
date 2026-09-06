# Same Package Twice

Gallery example 12 of twenty — **one definition, two instances**. The
`new Root()` demo: both mounts run `chained-summarizer`, each carries its own
`data.overrides`, and the package on disk is never written.

| Node | One line |
| --- | --- |
| `in1` **Question** | where the request enters |
| `mount-terse` **Instance A — terse** | `chained-summarizer`, overridden to compress to twelve words |
| `mount-analogy` **Instance B — analogy** | `chained-summarizer`, overridden to answer through an everyday analogy |
| `out1` **Answer** | renders instance B's sentence |

**Chained, not joined.** There is no way to fan two mount results back into one
node: every input port in the catalogue is `maxConnections: 1` except
`function.format_report.candidate`, which ignores its edges and reads
`worker_results` (gallery ticket 14). So instance B reads instance A's answer,
which is a fair demonstration anyway — the two instances answer *different*
questions and still differ in exactly the way their overrides say.

## The override shape

`docs/decisions/mount-overrides.md`, and nothing invented here:

```json
"overrides": { "<childNodeId>": { "<fieldKey>": <JSON value> } }
```

Both mounts override the same child node id and the same field key —
`shorten1.systemPrompt` — which is the cleanest possible statement of the
point: same class, same field, two instances, two values.

- Keys are the **child document's own** node ids (`in1`, `summarise1`,
  `shorten1`, `out1`), because titles are display text and are not unique.
- The merge happens in `apply_mount_overrides()` on an in-memory copy, before
  the child compiles. The compile seam stays one-directional; nothing is
  written back.
- A misspelled child node id **warns and runs the package default** rather than
  failing the run. Measured, on a copy of this document with `shortn1`:

  > Mount override — chained-summarizer: override targets unknown child node
  > "shortn1" — the package default ran

## Inherited versus overridden

`GET /api/workflows/same-package-twice/mounts/mount-terse` returns what this
instance actually runs; add `?inherited=true` and you get what it would run
if it overrode nothing — which is the package's own `shorten1` prompt, and is
what an inspector shows beside an overridden field and what a revert restores.
Both are asserted in `tests/`, against the real resolver.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy same-package-twice
openstategraph run workflows/same-package-twice "Describe a linked list."
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~17s. The two instances,
from `outputs`:

| Instance | Answer |
| --- | --- |
| A, terse | *A linked list is nodes pointing to the next, enabling sequential access.* (11 words) |
| B, analogy | *Imagine a treasure hunt where each clue is a folded piece of paper that tells you where the next clue is hidden, so you can keep adding or removing clues without moving the others, just by swapping the paper that points to the next location.* (43 words) |

Each obeys its own override and neither obeys the other's. And the thing the
example is really for:

```
$ shasum -a 256 workflows/chained-summarizer/workflow.json   # before
6fe426d961cd6bd9e089486f82fd5b6bbcfe36b6d419585146b931b60674cf69
$ shasum -a 256 workflows/chained-summarizer/workflow.json   # after
6fe426d961cd6bd9e089486f82fd5b6bbcfe36b6d419585146b931b60674cf69
```

Byte-identical. Two instances configured differently, one definition
untouched — which is what makes a mount a mount and not a fork.

## Tests

`tests/` asserts the two mounts name one package, that they override the same
key with different values, and that the resolver hands back the overridden and
the inherited document. It also pins the byte-level claim the way a test can:
the overrides live on **this** document, and `chained-summarizer`'s own
`shorten1` prompt is still its own.
