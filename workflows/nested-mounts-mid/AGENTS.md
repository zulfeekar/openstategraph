# Nested Mounts (middle)

The middle level of gallery example 11. It mounts `chained-summarizer` and
does nothing else, so the only thing this document contributes is **a level**.

| Node | One line |
| --- | --- |
| `in1` **Question** | where the request enters |
| `mount-inner` **Chained Summarizer** | mounts gallery example 1, by reference |
| `out1` **Answer** | renders what came back |

It ships as its own package rather than as a fixture because a mount points at
a **package slug**: there is no way to nest one document inside another except
by both of them existing on disk. That is the same by-reference rule that makes
`?w=nested-mounts/mount-mid` a different thing from `?w=nested-mounts-mid` —
the first is an instance, the second is the class.

Runnable on its own, and worth running on its own once: it is the two-level
control for the three-level example next door.

```
openstategraph run workflows/nested-mounts-mid "Explain what a compiler does, briefly."
```

Everything else about this pair — the addresses, the self-mount refusal, what
`outputs` and `attempts` do across a mount boundary — is written once, in
`workflows/nested-mounts/AGENTS.md`.

There is no `tests/` here for the same reason. This document's pin, its shape
and its place in the chain are asserted in
`workflows/nested-mounts/tests/test_nested_mounts_document.py`, which reads all
three documents; a second file re-reading one of them would be duplicated
knowledge, not extra coverage.
