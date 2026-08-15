# Knowledge Lookup QA

Gallery example 15 of twenty — **retrieval as a plain tool binding**, and the
smallest graph that is honestly a RAG example. No loop, no router, no rewrite.

| Node | One line |
| --- | --- |
| `in1` **Question** | where the request enters |
| `t-knowledge` **Vault handbook** | `tool.knowledge-lookup`, bound to the agent's `tools` bus |
| `answer1` **Vault Registrar** | answers from the handbook, and says which topic it read |
| `out1` **Answer** | renders the answer |

## The store is the package

`knowledge/` holds five Markdown topic docs about the **Meridian Seed Vault**,
a place that does not exist. That is deliberate and it is the whole test: every
figure in an answer is either in these files or invented, with no third
possibility, so a run that answers correctly has demonstrably *fetched*.

| Topic | What it holds |
| --- | --- |
| `accessions` | what a lot must carry to get an id; minimum viable quantities |
| `storage-tiers` | the three vaults, their conditions, and the promotion rules |
| `viability-testing` | test intervals per tier, and the germination thresholds |
| `withdrawals` | who may authorise, ceilings, and why returns are never re-shelved |
| `duplication` | the off-site safety copy, and what Tier 3 will not accept without one |

The docs cross-reference each other by topic name, which is how progressive
disclosure earns its keep: an answer about Tier 3 promotion needs
`storage-tiers` *and* `duplication`, and the model fetches the second because
the first named it — not because a prompt author guessed it would be needed.

## Deliberately not vector search

`tool.knowledge-lookup` is three-tier progressive disclosure over Markdown
topic docs: a free index of topic names and one-line hints, then the topic, and
nothing embedded anywhere. `docs/decisions/knowledge-architecture.md` argues it;
the reason it matters to a *gallery* is that no example may imply semantic
retrieval this platform does not do. The store whose `recall` silently ignores
`query=` is the memory store, and that is organisms-first-class ticket 26.

It is also the one node type with `maxInstances: 1` — a second knowledge node
would be a second name for one store.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy knowledge-lookup-qa
openstategraph run workflows/knowledge-lookup-qa \
  "How often is a Deep Vault lot germination-tested, and what germination rate forces a regeneration?"
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~6s:

> The Deep Vault lot is germination-tested every 20 years (see
> **viability-testing**). A regeneration is triggered when the germination rate
> falls **below 70 %** (see **viability-testing**).

Both figures are correct and both are unguessable. The tool calls are visible
in the recording — `openstategraph threads show <thread-id>` replays it without
calling a model or a tool:

```
tool: Error: No knowledge for topic ''. Available topics:
- accessions — …
- viability-testing — …
tool: Viability testing — how often a lot is germination-tested, …
```

Two calls: the index, then the topic. Which is the shape the design intends —
and note how the index arrives. **The free index tier is delivered as an
`Error:`**, because the only way to ask for it is to look up a topic that is
not there. It worked here; a weaker model that treats "Error" as a dead end
would stop instead of reading the menu. Gallery ticket 29.

## Pairs with example 8

`agentic-rag-rewrite` grades what it fetched and rewrites the question when the
answer does not hold up. This one merely fetches. The pair is the point: the
retrieval mechanism is identical, and the loop is the only difference.

## Tests

`tests/` asserts the binding, the `maxInstances` rule, and that every topic doc
has an index hint and is reachable — the store's own contract, checked without
a model call. Whether the model reads what it fetched is what the smoke run and
its recording are for.
