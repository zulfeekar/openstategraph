# Nested Mounts

Gallery example 11 of twenty — **composition depth**, and the only example
whose point is that it has no point of its own. Three nodes:

| Node | One line |
| --- | --- |
| `in1` **Question** | where the request enters |
| `mount-mid` **Nested Mounts (middle)** | mounts `nested-mounts-mid`, which mounts something else |
| `out1` **Answer** | renders what came back |

Three documents, three levels:

```
nested-mounts          in1 → mount-mid ─┐
nested-mounts-mid                       └→ in1 → mount-inner ─┐
chained-summarizer                                            └→ in1 → summarise1 → shorten1 → out1
```

`nested-mounts-mid` ships beside this package and exists only to be the middle
level. `chained-summarizer` is gallery example 1, mounted **by reference** —
its bytes are not copied here and are not written by a run.

## What it exists to exercise

**That depth is not a special case.** A mount compiles its child at build
time and invokes it as one node; a child that is itself a mount is resolved
by that build, one level further down. Nothing in the document says "two
levels" — the second level is a fact about `nested-mounts-mid`, and this
document cannot tell.

The one place depth *is* a special case is naming. `GraphNames.absorb` folds
a grandchild's node names up through two mount ids so a frame from three
levels down can still say which card it is about, and the timing of that fold
(after `build()`, not after `factory()`) is a bug this repository has already
paid for once — see the comment at `compile/node_runtime.py:2060`.

## Drill-in addressing

A mount node id is the unit of an address, not the package slug, because two
mounts of one package must be tellable apart (`src/core/model/MountAddress.ts`).
So this example has three addresses:

| Address | Opens |
| --- | --- |
| `?w=nested-mounts` | this document — the class |
| `?w=nested-mounts/mount-mid` | the `nested-mounts-mid` **instance** at `mount-mid` |
| `?w=nested-mounts/mount-mid/mount-inner` | the `chained-summarizer` instance two levels in |

Each resolves over `GET /api/workflows/nested-mounts/mounts/mount-mid/mount-inner`,
which walks the segments applying each level's `overrides` in turn. Exercised
in `tests/` against `resolve_mount_document` directly, so the claim in this
table is checked rather than asserted.

## The self-mount

Point `mount-mid` at `nested-mounts` and the compiler refuses — verbatim:

```
Workflow 'nested-mounts' includes itself through its subgraphs
(nested-mounts -> nested-mounts); a subgraph cycle can never terminate
```

`openstategraph run` prints exactly that line and nothing else. Two things
about *when* it arrives are worth knowing before you rely on it:

- It is a **build-time** refusal (`NodeRuntime._subgraph`, walking
  `_ancestry`), so it costs no tokens and cannot be reached at run time.
- **`openstategraph validate` does not catch it.** The validator plans one
  document and has no document loader, so a self-mounting package reports
  `VALID` — as does a mount naming a package that does not exist. Measured
  while building this example; gallery ticket 27.

The editor-side guard — refusing the drag before it becomes a node — is
organisms-first-class ticket 10, and is not built.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy nested-mounts
openstategraph run workflows/nested-mounts "Explain what a compiler does, briefly."
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~8s:

> A compiler checks source code for errors, translates it into optimized
> machine code or an intermediate representation, and produces a standalone
> executable or library that can run without the original code or compiler.

One sentence, which is `chained-summarizer`'s contract holding through two
layers of indirection. Two things the `--json` result shows about mounts:

- `outputs` holds **this document's** nodes only — `in1`, `mount-mid`, `out1`.
  The middle document's `mount-inner`, and the summariser's two agents, are
  not there. A mount is one isolated step: task in, answer out.
- `attempts` is `2` — the two model calls made three levels down. The counter
  is graph-wide (gallery ticket 21) and it crosses the mount boundary, which
  is worth knowing before treating it as a revision count.

## What a preview does not show

`openstategraph graph workflows/nested-mounts` renders three boxes. `xray=True`
expands a LangGraph subgraph, but a mount is invoked *inside* a node function,
so no preview of any depth shows the composition — gallery ticket 28.

## Tests

`tests/` asserts the chain of documents, the three addresses through the real
resolver, and that the self-mount is not on disk. All zero-token: whether the
answer is a good sentence is `chained-summarizer`'s question, already recorded
there.
