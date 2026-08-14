# Agentic RAG Rewrite

Gallery example 8 of twenty — the one loop whose `revise` edge lands on a node
that **reshapes the question** instead of the node that produced the answer.

| Node | One line |
| --- | --- |
| `in1` **Vague question** | where a question too loose to look up enters |
| `rewrite1` **Rewriter** | turns it into a question the handbook could answer |
| `know1` **Handbook** | the package's own `knowledge/` store, as a tool |
| `retrieve1` **Retriever** | reads topics and answers from them, never from memory |
| `grader1` **Grounding review** | passes a grounded answer, sends an ungrounded one back |
| `out1` **Grounded answer** | renders whatever passed |

```
in1 ─▶ rewrite1 ─▶ retrieve1 ─▶ grader1 ──pass──▶ out1
        ▲                          │
        └───────── feedback ───────┘ revise
```

## Wiring order is the constraint

`agent.prompt` takes exactly one edge, so the rewriter must sit **upstream** of
the retriever — the retriever's prompt *is* the rewritten question. A rewriter
placed beside the retriever could not hand it anything.

## The knowledge store is not vector search

`tool.knowledge-lookup` is three-tier progressive disclosure over the Markdown
files in `knowledge/`: an index of topics with one-line hints, then the whole
document for a named topic. An unknown topic answers with the menu, so a wrong
guess costs one round-trip. There is no embedding, no similarity, no chunking —
by design (`docs/decisions/knowledge-architecture.md`).

The store is a fictional company (Northwind Robotics) on purpose: every figure
in it — Crucible's 5-minute first response, rung 2's 4-hour hold, the Thursday
hotfix train — exists nowhere else, so an answer containing one was *read*, and
an answer that sounds plausible without one was *invented*.

**The Knowledge atom is a declaration, not the binding.** A non-empty
`knowledge/` directory attaches the lookup tool to every agent in the package
ambiently (`ambient_knowledge_tool`), so `rewrite1` can also reach it even
though no edge says so. `know1` is on the canvas because a reader should be able
to see where the second brain is; unwiring it would change nothing at runtime.

## Six attempts for two laps

`attempts` is one counter for the whole graph and *both* agents increment it, so
one lap of this loop costs **two** attempts. `maxAttempts: 6` therefore buys
three laps, not six. See gallery ticket 21.

## Smoke run

```
openstategraph run workflows/agentic-rag-rewrite "How do I get something fixed fast?"
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~29s, `attempts: 4` — two
laps, so **one rewrite**:

| Lap | The rewriter asked | The retriever answered |
| --- | --- | --- |
| 1 | "In the escalation-paths handbook, what is the target response time in minutes for a Severity-1 incident?" | "the handbook does not." |
| 2 | "According to the escalation-paths, what is the maximum response time for a P1 incident?" | quoted `escalation-paths` — rung 3, Duty Commander, no time limit |

`decisions` is `{"grader1": "pass"}`. Both rewrites are visible in
`threads show`; `RunResult.outputs["rewrite1"]` holds only the last one.

**This is the run that answers organisms-first-class 37** (*may a grader's
revise edge reshape the question?*). It answers **yes**, and shows why the
alternative could not have worked: lap one failed because the question was
aimed at a topic that does not carry that figure. Sending the grader's feedback
to the *answer's producer* would have re-run the same lookups against the same
framing. Changing the question is the only move that could change the answer.

One condition comes with the yes: the grader's feedback is written *about an
answer*, so a node receiving it on a `feedback` port must be told to translate
it into a change of *question*. `rewrite1`'s prompt says so in as many words.
Without that sentence the edge is legal and semantically mismatched.
