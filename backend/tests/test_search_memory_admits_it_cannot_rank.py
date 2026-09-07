"""`search_memory` takes a `query` — it must not pretend to have used it.

`organisms-first-class/26`. `store.search(namespace, query=…, limit=4)` is only
a relevance search when the store was built with an `index={"embed": …}`.
None of `build_store()`'s three backends is, so `query=` was accepted and
silently dropped: the model asked for the closest four memories and got an
arbitrary four, with nothing anywhere saying so.

These tests drive the **tool**, not the store. A test asserting that
`build_store()` returns a store, or that `InMemoryStore` ignores `query`, stays
green against a `search_memory` that still claims relevance it did not compute.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from openstategraph.memory import memory_tools


class S(TypedDict, total=False):
    out: str


def _run_in_graph(fn, *, store, config) -> dict[str, Any]:
    builder = StateGraph(S)
    builder.add_node("n", fn)
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    return builder.compile(store=store).invoke({}, config)


CONFIG = {"configurable": {"user_email": "me@example.com", "thread_id": "t1"}}

FACTS = [
    "cats are furry",
    "the capital of France is Paris",
    "python is a language",
    "zebras have stripes",
    "my birthday is in March",
    "I like broccoli",
]


def _fill(save, store) -> None:
    for fact in FACTS:
        _run_in_graph(lambda s, f=fact: {"out": save.invoke({"fact": f})},
                      store=store, config=CONFIG)


def _embed(texts: list[str]) -> list[list[float]]:
    """A deterministic stand-in for an embedder: one axis per keyword.

    Enough to make `query=` genuinely order the results, which is the only
    thing the ranked direction of this test needs.
    """
    axes = ("broccoli", "zebra", "paris")
    return [[float(word in text.lower()) for word in axes] for text in texts]


class TestUnrankedSearchSaysSo:
    def test_a_store_with_no_index_reports_that_the_query_did_not_rank(self) -> None:
        store = InMemoryStore()
        save, search, _ = memory_tools()
        _fill(save, store)

        answer = _run_in_graph(
            lambda s: {"out": search.invoke({"query": "which vegetable do I like"})},
            store=store, config=CONFIG,
        )["out"]

        # The evidence the tool has: six facts saved, four returned, and the
        # one the query names is not among them.
        assert "broccoli" not in answer
        # So it must not present them as the closest matches.
        assert "not ranked" in answer.lower()

    def test_an_indexed_store_ranks_and_claims_nothing_extra(self) -> None:
        store = InMemoryStore(index={"embed": _embed, "dims": 3})
        save, search, _ = memory_tools()
        _fill(save, store)

        answer = _run_in_graph(
            lambda s: {"out": search.invoke({"query": "broccoli"})},
            store=store, config=CONFIG,
        )["out"]

        assert "broccoli" in answer
        assert "not ranked" not in answer.lower()

    def test_an_empty_scope_does_not_claim_a_query_was_matched(self) -> None:
        store = InMemoryStore()
        _, search, _ = memory_tools()

        answer = _run_in_graph(
            lambda s: {"out": search.invoke({"query": "anything at all"})},
            store=store, config=CONFIG,
        )["out"]

        # Nothing was matched *or* not matched — there is nothing saved. The
        # old wording ("No saved memories match.") was a claim about a
        # comparison that never happened.
        assert "match" not in answer.lower()
