"""Shared test doubles.

Lives in `conftest.py` so pytest puts it on the path for every test module
(the suite deliberately has no `__init__.py` — see `pytest.ini`), and so
`RespondingModel` has one owner. It previously had five copies across the
graph-shape test modules (`test_orchestrator_graph`,
`test_intent_routed_workflow`, `test_chinook_demo_file` and two since-removed
workflow-file suites), each carrying a docstring pointing at one of the
others as the original. They had already drifted: two dropped the `calls`
list, one dropped `bind_tools`, and only one still recorded *why* the fake
is predicate-driven. That is the failure mode the rule against duplicated
knowledge names — the `object.__setattr__` workaround below is a real fact
about the library, and five copies is how one of them ends up wrong.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator

import os

import pytest

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

# The suite opts OUT of the durable checkpointer — explicitly, the same way a
# stateless deployment would, rather than through a private hook.
#
# Since ticket 05 the checkpointer defaults to a sqlite file under the
# workflows root, and `api/main.py` ends with `app = create_app()` for
# uvicorn's benefit — so merely *importing* a test module that imports it
# would write `workflows/.openstategraph/checkpoints.sqlite` into this
# checkout. That happens at collection time, before any fixture runs, which is
# why this is a module-level statement in `conftest.py` (imported first) and
# not an autouse fixture. A test suite must not leave files around.
#
# `setdefault`, so a developer who exports a real path still gets it, and the
# tests that are *about* the default (`test_persisted_checkpointer.py`) repoint
# or delete the variable through `monkeypatch` — which is what keeps the
# default exercised rather than hidden.
os.environ.setdefault("OPENSTATEGRAPH_CHECKPOINT_PATH", "memory")

# And the Store, for exactly the same reason and by exactly the same mechanism
# — since install-experience wave 2 it is durable by default too, so without
# this the suite would leave `workflows/.openstategraph/memory.sqlite` behind.
# `test_persisted_memory_store.py` is the suite that is *about* the default and
# clears this through `monkeypatch`.
os.environ.setdefault("OPENSTATEGRAPH_MEMORY_PATH", "memory")

#: A predicate over the model's incoming context, and the reply to give.
RouteRule = tuple[Callable[[str], bool], str]


def any_chat_model() -> GenericFakeChatModel:
    """*A* model, for a test that needs one and does not care which.

    `object()` and `SimpleNamespace(name="stub")` used to serve here, and
    stopped being enough when summarization became on by default: building an
    agent now constructs `SummarizationMiddleware`, which asks the model for
    `_llm_type` (to tune its token counter) and for `profile` (to decide
    whether a fractional trigger is even expressible). Those are questions
    only a real chat model can answer — and in production the model always is
    one, either a `BaseChatModel` or the `UnconfiguredProvider` stand-in,
    never a bare object. The sentinel was a fiction the compiler had simply
    never called.

    Answers nothing: these tests stub the agent tier, so the model is reached
    for its *shape*, never for a reply.
    """
    return GenericFakeChatModel(messages=iter([]))


class RespondingModel(GenericFakeChatModel):
    """Answers by matching a **predicate** over the incoming message, not call order.

    A queue-based fake (`iter(["a", "b"])`) would make a test's correctness
    depend on which of two concurrently dispatched tasks happens to call the
    model first — which `Send` does not guarantee. Matching on content
    instead means the answer is deterministic regardless of dispatch order.

    A predicate rather than a substring, because substring containment
    cannot express what these tests actually need to distinguish: "the
    report has only task-1" is a *negative* condition (task-2 absent), and a
    grader's own prompt legitimately echoes the original question into its
    context, so a short worker-routing string is a genuine, unavoidable
    substring of the grader's call too. A predicate says exactly what is
    meant instead of fighting string containment to approximate it.

    `object.__setattr__` is not a style choice: `GenericFakeChatModel` is a
    Pydantic model and ordinary attribute assignment in `__init__` is
    refused.
    """

    rules: list[RouteRule] = []
    default: str = "PASS"
    #: Every context the model was called with, in order — what a test
    #: asserts against when it needs to prove *what the node was told*,
    #: not just what came back.
    calls: list[str] = []

    def __init__(self, rules: list[RouteRule], default: str = "PASS"):
        super().__init__(messages=iter([]))
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "default", default)
        object.__setattr__(self, "calls", [])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        self.calls.append(content)
        answer = self.default
        for predicate, reply in self.rules:
            if predicate(content):
                answer = reply
                break
        return self._reply(answer)

    def _reply(self, text: str):  # noqa: ANN001
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001
        """`GenericFakeChatModel.bind_tools` raises by default.

        Every caller needs this for the same reason, stated once here rather
        than five times: `create_agent` calls `bind_tools` for any agent
        given tools (the Chinook document binds real ones), and
        `create_deep_agent` calls it *even with* `tools=[]`, because it
        always attaches its own filesystem/subagent tools. The fake still
        answers purely from message content; it never looks at what was
        bound.
        """
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)


class BlockRespondingModel(RespondingModel):
    """`RespondingModel`, but it answers in **content blocks** rather than a string.

    Exists because the string-shaped fake cannot express the shape that broke
    the product (the-editor-makes-a-real-package tickets 03 and 06). LangChain
    documents `content` as "loosely-typed, supporting strings and lists of
    untyped objects", and an Anthropic `AIMessage` in particular "can either be
    a single string or a list of content blocks". Adding `"messages"` to
    `stream_mode` — which both shipped UIs do and no test did — is enough to
    switch a settled message from

        content="144"

    to

        content=[{"type": "text", "text": "144", "index": 0}]

    Every fake in this suite answered in the first shape, so every test agreed
    with a runtime that was wrong in the second: `/api/runs` answered `49`
    while `/api/runs/stream` answered the *question*, and 2000 tests stayed
    green.

    `reasoning` puts a thinking block ahead of the text, because a thinking
    model's private deliberation rides in the same list and must not reach the
    answer.
    """

    reasoning: str = ""

    def __init__(self, rules: list[RouteRule], default: str = "PASS", reasoning: str = ""):
        super().__init__(rules, default)
        object.__setattr__(self, "reasoning", reasoning)

    def _reply(self, text: str):  # noqa: ANN001
        from langchain_core.outputs import ChatGeneration, ChatResult

        blocks: list[dict[str, object]] = []
        if self.reasoning:
            blocks.append({"type": "thinking", "thinking": self.reasoning, "signature": "sig"})
        # `index` is present on real streamed blocks and absent on settled
        # ones; carrying it keeps this honest about what aggregation produces.
        blocks.append({"type": "text", "text": text, "index": len(blocks)})
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=blocks))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        """Block-shaped chunks, because the inherited one refuses to emit them.

        `GenericFakeChatModel._stream` raises *"Expected content to be a
        string"* outright, so a block-shaped fake cannot stream at all without
        this — and streaming is the only path that matters here.

        Each chunk carries a one-block list rather than a bare string, which
        is what a real provider sends and what makes the aggregate settle as a
        block *list*. That aggregate is the whole point: it is the shape the
        product got wrong.
        """
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        message = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for index, block in enumerate(message.generations[0].message.content):
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(content=[{**block, "index": index}])
            )
            if run_manager:
                run_manager.on_llm_new_token(block.get("text", ""), chunk=chunk)
            yield chunk


@pytest.fixture(autouse=True)
def _fresh_process_tool_layer():
    """No process-lifetime cache may outlive the test that populated it.

    `api.registries` caches the built-in + installed-plugin tool layer for the
    life of the process, because rebuilding it was 82% of every
    `runtime_for` call (`tests/test_no_repeated_work.py` measures it). Tests
    fake installed entry points with `monkeypatch`, so without this the first
    test to build the registry would decide what every later test sees.
    """
    from openstategraph.api.registries import reset_process_tool_layer

    reset_process_tool_layer()
    yield
    reset_process_tool_layer()


@pytest.fixture(autouse=True)
def _fresh_provider_catalogue():
    """The same rule, for the other process-lifetime cache.

    `providers._CATALOGUE` memoises the registered providers *and* whatever
    config file was discovered when it was first built. Four test modules
    reset it; roughly twenty do not, so every module that sets a provider
    variable inherited whatever an earlier one had built. That is
    order-dependence by construction — green today only because of collection
    order (reviews-2026-08-14 ticket 10).

    Global rather than per-module for the reason the tool layer above is: a
    cache that outlives its test decides what the next test sees, and the next
    test did not ask.
    """
    from openstategraph.providers import reset_provider_catalogue

    reset_provider_catalogue()
    yield
    reset_provider_catalogue()


@pytest.fixture(autouse=True)
def _no_ambient_config_file(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A developer's exported `OPENSTATEGRAPH_CONFIG` is not part of the suite.

    `find_config_file` checks `OPENSTATEGRAPH_CONFIG` before anything else, so
    a shell that exports it — pointing at a real project's file — silently
    rewrites the catalogue for every test that does not set its own. Deleted
    by default; a test that wants one sets it, and `monkeypatch` puts the
    developer's back afterwards (reviews-2026-08-14 ticket 10).

    The ticket also named "ambient config discovery walks up from cwd". It
    does not: `find_config_file` looks in `base` only, never in its parents,
    so a stray file *above* the checkout was never reachable. The exported
    variable was one half; **this checkout's own file is the other**, and it
    arrived with install-experience T10.

    `openstategraph.yaml` is committed at the repository root now — it is where
    the gallery's Ollama-cloud pin moved to when the 22 examples stopped naming
    a vendor — and `find_config_file` looks in the working directory, which for
    this suite is that root. Left alone it would make one operator decision the
    default for two and a half thousand tests, most of which are about what the
    *rules* answer.

    So the variable is pointed at a path that does not exist, which
    `find_config_file` documents as `None` — the explicit setting wins over the
    search, so nothing is discovered, and a test that wants a config still sets
    the variable to its own file and overrides this. The empty temporary file
    that would do the same job is a file, and a file has contents somebody will
    eventually put something in.

    **The memoised config is dropped on both sides too**, which the catalogue
    fixture above has always done and this one did not. `config_file._ACTIVE`
    is a process-lifetime cache exactly like `providers._CATALOGUE`, so a test
    that pointed `OPENSTATEGRAPH_CONFIG` at its own file left that file's
    `default_model:` deciding for every later test that did not set one — the
    same order-dependence, one module along.
    """
    from openstategraph.config_file import reset_active_config

    monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(Path(__file__).parent / "no-such-config.yaml"))
    reset_active_config()
    yield
    reset_active_config()


@pytest.fixture(autouse=True)
def _release_services_this_test_opened() -> Iterator[None]:
    """Close every `WorkflowServices` a test built, at that test's teardown.

    Install-experience ticket 11's second half. `create_app()` resolves the
    checkpointer eagerly — deliberately, so the durability line reaches the
    operator at startup rather than at the first approval — and there are over
    a hundred `create_app(` call sites in this suite, none of which close. The
    suite only escaped the consequence because it opts out of durable defaults
    at the top of this file: with `OPENSTATEGRAPH_CHECKPOINT_PATH=memory` the
    handle is an in-memory saver rather than a descriptor. Every test that
    repoints those variables at a real file — and they exist, because the
    defaults have to be exercised somewhere — opened one and dropped it.

    **Patching the class, not `create_app`.** Test modules import `create_app`
    by name at import time, so replacing the module attribute would miss every
    one of them; the class is looked up at construction. Wrapping `__init__`
    catches the MCP transport and bare `WorkflowServices(...)` uses too, which
    are the same leak wearing a different hat.

    Safe against a services object that outlives the test: `close()` is
    idempotent and both properties are lazy, so a later use resolves a fresh
    saver rather than a closed one — which is exactly the resurrection
    behaviour `WorkflowServices.close` documents on itself.
    """
    import functools
    import weakref

    from openstategraph.api.services import WorkflowServices

    original = WorkflowServices.__init__
    live: list[weakref.ReferenceType[WorkflowServices]] = []

    @functools.wraps(original)
    def remember(self: WorkflowServices, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)  # type: ignore[arg-type]
        live.append(weakref.ref(self))

    WorkflowServices.__init__ = remember  # type: ignore[method-assign]
    try:
        yield
    finally:
        WorkflowServices.__init__ = original  # type: ignore[method-assign]
        for reference in live:
            services = reference()
            if services is not None:
                services.close()


# --- driving the run fold ---------------------------------------------------
#
# `_run_frames` and `_stream_run` are **async generators** since
# `async-first/02`, and the suite scripts them by hand: eighteen modules build
# a stub graph whose `stream()` returns a hand-written list of chunks and pull
# the frames through a `for` loop. Both halves of that fold move here rather
# than into eighteen copies, for the reason the docstring at the top of this
# file already gives — a test double with five copies is a test double with
# one wrong copy.


class ScriptedGraph:
    """A sync-scripted stub graph, presented to the async fold.

    The stubs the suite writes are the honest shape for what they assert: a
    list of chunks and a `get_state`. Nothing about them is asynchronous, and
    making eighteen modules `async def` their `stream` would be eighteen
    copies of this adapter with no assertion behind any of them.

    So the adapter lives once. `astream` replays the wrapped stub's `stream()`,
    `aget_state` its `get_state()`, and everything else — `get_graph`, the
    recorded `stream_kwargs` a few modules assert on — passes through
    untouched, which is what keeps those assertions about the fold rather than
    about this class.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def astream(self, *args: object, **kwargs: object) -> object:
        inner = self._inner

        async def replay() -> object:
            for chunk in inner.stream(*args, **kwargs):  # type: ignore[attr-defined]
                yield chunk

        return replay()

    async def aget_state(self, config: object) -> object:
        return self._inner.get_state(config)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


def drive_fold(frames: object) -> list[str]:
    """Every frame an async fold yields, as a list, from synchronous test code.

    One `asyncio.run` per drive, so nothing leaks between tests. Pytest is not
    configured with an async plugin here and this deliberately does not add
    one: the assertions are about the frames, not about the loop, and a driver
    is cheaper than a plugin the whole suite would then depend on.
    """
    import asyncio

    async def collect() -> list[str]:
        return [frame async for frame in frames]  # type: ignore[union-attr]

    return asyncio.run(collect())


class FoldPump:
    """An async fold, pulled one frame at a time from synchronous test code.

    `drive_fold` drains; this is for the tests that must stop **part way** —
    the Stop tests, which assert on what the fold did and did not do after the
    consumer walked away. One event loop for the life of the pump, because the
    generator is suspended between calls and resuming it on a second loop is
    undefined.

    `close()` is the explicit-`aclose()` half of a stop, which reaches the fold
    as `GeneratorExit`. The live half is a cancelled `__anext__`, which reaches
    it as `CancelledError`; `stop_when_client_leaves` is what does that, and it
    has its own tests.
    """

    def __init__(self, frames: object) -> None:
        import asyncio

        self._loop = asyncio.new_event_loop()
        self._frames = frames.__aiter__()  # type: ignore[union-attr]

    def next(self) -> str:
        return self._loop.run_until_complete(self._frames.__anext__())

    def close(self) -> None:
        try:
            self._loop.run_until_complete(self._frames.aclose())
        finally:
            self._loop.close()


def drive_node(run: Any, state: Any) -> Any:
    """The update an `async def` node body returns, from synchronous test code.

    `async-first/06` made the long-running node families (`_agent`, `_worker`,
    ...) `async def`, and the suite calls those builders directly — a factory
    returns a closure and the test runs it. One `asyncio.run` per drive, for
    the reason `drive_fold` above gives: the assertions are about the update,
    not about the loop, and a driver is cheaper than an async plugin the whole
    suite would then depend on.

    Total, so a test that does not care which kind it holds does not have to:
    a synchronous body is simply called.
    """
    import asyncio
    import inspect

    result = run(state)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


@pytest.fixture()
def tiny_db(tmp_path: Path) -> Path:
    """The three-row `genre` table the evaluation harness's tests grade against.

    Here rather than in one of them because two modules now need it
    (`test_evaluation.py` and `test_the_same_question_twice.py`), and a fixture
    imported from a sibling test module shadows the parameter that receives it
    — the lint gate says so, and a second copy of these eight lines is the
    duplication of *knowledge* CLAUDE.md's DRY rule actually forbids.
    """
    import sqlite3

    path = tmp_path / "tiny.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE genre (id INTEGER, name TEXT, revenue REAL)")
    conn.executemany(
        "INSERT INTO genre VALUES (?, ?, ?)",
        [(1, "Rock", 826.65), (2, "Latin", 382.14), (3, "Metal", None)],
    )
    conn.commit()
    conn.close()
    return path
