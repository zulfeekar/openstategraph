#!/usr/bin/env python3
"""Where one turn's wall clock actually goes — model, tool, or ours.

`launch-readiness/109` asks one question and it is not "be fast":

    Of the wall-clock time in one turn, how much is model latency we chose,
    and how much is **ours** — scheduling, serialisation, waiting on something
    that could have been concurrent, or work done twice?

This is the instrument that answers it, committed for the same reason
`scripts/measure_setup_path.py` was (`launch-readiness/113`): so the next
person re-measures instead of re-arguing.

    python3 scripts/measure_turn.py workflows/chinook-assistant \
        --question "..." --passes 2

**Three clocks, and the point is that they are compared rather than mixed.**

- **The frame clock** — `elapsedMs` / `seq`, minted server-side by
  `api/frame_clock.py` (`memory-and-replay` 46) at the moment the frame is
  built. This is the ticket's "per-node wall clock, taken at the point the
  frames are emitted rather than in the browser", and it is why this script
  needs no browser and no timeline panel — `launch-readiness/108` says that
  panel is not yet trustworthy, and `105` says `RuntimeClient` can drain a
  whole TCP chunk synchronously, so a browser-side arrival time is not
  evidence of anything.
- **The model clock** — LangChain's own `on_llm_start` / `on_llm_end`, from a
  handler installed globally through `register_configure_hook`, so it covers
  *every* model call in the graph: a router's, a grader's, and each ReAct lap
  of every agent, without any node having to opt in.
- **The tool clock** — `on_tool_start` / `on_tool_end`, same handler.

**The arithmetic, stated so it can be argued with.** Model and tool intervals
are **merged before they are summed**, because a fan-out runs several at once
and adding their durations would credit the graph with more seconds than the
turn contained. What is left after subtracting the merged busy time from the
wall clock is the bucket this ticket calls *ours*: scheduling, serialisation,
state merging, frame building, and any waiting that was not a provider's.

    ours = wall − |model ∪ tool intervals|

That is an upper bound on our overhead and a deliberately unflattering one:
anything the graph did concurrently *with* a model call is charged to the
model, never to us.

**What "ours" does and does not cover.** It is `wall` minus everything
LangChain's callback surface saw — model calls and LangChain tool calls. I/O a
node performs *outside* that surface (a package function calling a warehouse
directly, say) is not a provider call as far as this instrument is concerned
and therefore lands in "ours". That is the safe direction to be wrong in: it
inflates our own bucket rather than hiding it, and a large `gaps` figure is a
prompt to look at what the nodes are doing rather than a verdict.

**A live model, and therefore spend.** `--passes 2` is the floor, not a
default worth lowering: the single most valuable finding of 2026-08-27 was not
a latency, it was that three runs of one question gave three different
answers. One pass measures nothing about a system whose laps are chosen by a
model.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent


def _prepare_environment(package: Path, env_file: Path | None) -> None:
    """The three fixes without which every live run fails silently.

    Recorded in CLAUDE.md and in this map's handoffs, and worth doing here
    rather than in a shell prelude, because a measurement that quietly ran
    against a local model is worse than no measurement: "Ollama means Ollama
    **cloud**, never a local model", and a weak local model turns a wiring bug
    and a capability gap into the same symptom.
    """
    sys.path.insert(0, str(REPO / "backend"))
    from openstategraph.dotenv import load_env_file

    load_env_file(Path.cwd())
    load_env_file(package)
    if env_file is not None:
        # An explicit file wins, and it is usually what you want: a demo's
        # credentials live beside the demo, and this script deliberately does
        # not run from inside a package checkout.
        for line in env_file.expanduser().read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            os.environ[name.strip()] = value.strip().strip('"').strip("'")
    # A daemon on this machine must not be able to answer for the cloud.
    os.environ.pop("OLLAMA_HOST", None)
    os.environ.pop("OLLAMA_ENDPOINT", None)
    os.environ["OPENSTATEGRAPH_WORKFLOWS_ROOT"] = str(package.parent)


class Span:
    """One provider call: what it was, and the two monotonic stamps."""

    __slots__ = ("kind", "name", "start", "end")

    def __init__(self, kind: str, name: str, start: float) -> None:
        self.kind = kind
        self.name = name
        self.start = start
        self.end = start

    @property
    def seconds(self) -> float:
        return self.end - self.start


def _merged(spans: list[Span]) -> float:
    """Seconds covered by the union of these intervals.

    The union, never the sum: two tool calls in one superstep overlap, and
    summing them would report a turn as busier than it was long — which is how
    an "ours" bucket goes negative and a measurement stops being believable.
    """
    if not spans:
        return 0.0
    ordered = sorted(spans, key=lambda s: s.start)
    total = 0.0
    start, end = ordered[0].start, ordered[0].end
    for span in ordered[1:]:
        if span.start > end:
            total += end - start
            start, end = span.start, span.end
        else:
            end = max(end, span.end)
    return total + (end - start)


def _install_probe() -> tuple[Any, list[Span]]:
    """A callback handler on every model and tool call in the process.

    `register_configure_hook` is LangChain's own mechanism for this — the same
    one its tracing uses — so nothing in `openstategraph/` is patched, and a
    number that came out of here cannot be an artefact of a monkeypatched
    seam.
    """
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.tracers.context import register_configure_hook

    spans: list[Span] = []
    open_spans: dict[Any, Span] = {}

    class Probe(BaseCallbackHandler):
        raise_error = False

        def _open(self, kind: str, name: str, run_id: Any) -> None:
            span = Span(kind, name, time.monotonic())
            open_spans[run_id] = span
            spans.append(span)

        def _close(self, run_id: Any) -> None:
            span = open_spans.pop(run_id, None)
            if span is not None:
                span.end = time.monotonic()

        def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: Any = None, **kw: Any) -> None:
            self._open("model", str((serialized or {}).get("name") or "model"), run_id)

        def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: Any = None, **kw: Any) -> None:
            self._open("model", str((serialized or {}).get("name") or "model"), run_id)

        def on_llm_end(self, response: Any, *, run_id: Any = None, **kw: Any) -> None:
            self._close(run_id)

        def on_llm_error(self, error: Any, *, run_id: Any = None, **kw: Any) -> None:
            self._close(run_id)

        def on_tool_start(self, serialized: Any, input_str: Any, *, run_id: Any = None, **kw: Any) -> None:
            self._open("tool", str((serialized or {}).get("name") or "tool"), run_id)

        def on_tool_end(self, output: Any, *, run_id: Any = None, **kw: Any) -> None:
            self._close(run_id)

        def on_tool_error(self, error: Any, *, run_id: Any = None, **kw: Any) -> None:
            self._close(run_id)

    # The handler is the variable's **default**, not a value `set` into one
    # context. The run happens on uvicorn's own thread, and a thread starts
    # with a fresh context — a `set` here would be invisible there, and the
    # probe would silently record nothing at all, which reads exactly like a
    # graph that made no model calls.
    var: contextvars.ContextVar[Any] = contextvars.ContextVar(
        "osg_turn_probe", default=Probe()
    )
    register_configure_hook(var, True)
    return var, spans


class _Server:
    """A real socket, because a buffered transport cannot time a stream.

    `httpx.ASGITransport` drives the app to completion and hands back the
    whole body, so every frame "arrives" at once and the first-frame number is
    the last frame's. That is not a subtle distortion — it is the difference
    between measuring a stream and measuring a file. So this starts uvicorn on
    an ephemeral port in a thread of its own, and the client talks TCP.

    Started from the repository, never from inside a package checkout: this
    map's handoff records that `OPENSTATEGRAPH_STATE_DIR` does not isolate a
    server whose cwd is one.
    """

    def __init__(self) -> None:
        import threading

        import uvicorn

        from openstategraph.api.main import create_app

        config = uvicorn.Config(
            create_app(), host="127.0.0.1", port=0, log_level="warning", access_log=False
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            sockets = getattr(self._server, "servers", None)
            if self._server.started and sockets:
                port = sockets[0].sockets[0].getsockname()[1]
                return f"http://127.0.0.1:{port}"
            time.sleep(0.02)
        raise SystemExit("the measurement server did not start")

    def __exit__(self, *_exc: Any) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


async def _drive(base: str, document: dict[str, Any], question: str, model: str | None) -> dict[str, Any]:
    import httpx

    payload: dict[str, Any] = {"workflow": document, "question": question}
    if model:
        payload["model"] = model

    frames: list[dict[str, Any]] = []
    started = time.monotonic()
    async with httpx.AsyncClient(base_url=base, timeout=None) as client:
        async with client.stream("POST", "/api/runs/stream", json=payload) as response:
            response.raise_for_status()
            event = ""
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    body = json.loads(line.split(":", 1)[1].strip())
                    body["event"] = event
                    body["arrivedS"] = time.monotonic() - started
                    frames.append(body)
    return {"wall": time.monotonic() - started, "frames": frames, "origin": started}


def _node_spans(frames: list[dict[str, Any]]) -> tuple[list[tuple[str, float, float]], str]:
    """Per-node wall clock, and which clock it came from.

    A node's segment runs from the previous completion to its own `update`,
    which is what `update` means here — it "fires on completion", per
    `api/streaming.py`. Nested frames (`namespace`, a mount's insides) are
    folded onto the mount rather than listed twice.

    **`elapsedMs` is preferred and is usually not there.** The server-side
    frame clock stamps the first frame of a real stream and no other — see
    `launch-readiness/171`, filed from this instrument's own output — so the
    fallback is the client's arrival time, and the report says which was used
    rather than quietly mixing them. Over loopback, with a client that does
    nothing between reads but append to a list, arrival trails emission by
    well under a millisecond; it is not the browser measurement `105` warns
    about, where a whole TCP chunk is drained synchronously before anything is
    timestamped.
    """
    updates = [f for f in frames if f.get("event") == "update" and not f.get("namespace")]
    stamped = sum(1 for f in updates if f.get("elapsedMs") is not None)
    clock = "frame clock (elapsedMs)" if stamped == len(updates) and updates else (
        f"client arrival — only {stamped}/{len(updates)} updates carried elapsedMs"
    )
    out: list[tuple[str, float, float]] = []
    previous = 0.0
    for frame in updates:
        node = str(frame.get("node") or "?")
        if clock.startswith("frame"):
            now = float(frame["elapsedMs"]) / 1000.0
        else:
            now = float(frame["arrivedS"])
        out.append((node, previous, now))
        previous = now
    return out, clock


def _ours_breakdown(spans: list[Span], origin: float, wall: float) -> list[tuple[str, float]]:
    """Where the non-provider seconds sit, which is the whole question.

    Three places, and they mean three different things:

    - **head** — before the first provider call. Compile, tool import, skill
      read, and whatever the input node does. `launch-readiness/113` measured
      this path at 27 ms warm, so a head much larger than that is either a
      cold process or something else.
    - **gaps** — between one provider call ending and the next beginning.
      Scheduling, state merging, reducers, frame building, and any
      serialisation of work that had no dependency. This is the bucket a
      concurrency defect would live in.
    - **tail** — after the last provider call, up to the client seeing `done`.
      The ticket names this one explicitly: time between the last token and
      the `done` frame.
    """
    if not spans:
        return [("head", 0.0), ("gaps", 0.0), ("tail", wall)]
    ordered = sorted(spans, key=lambda s: s.start)
    head = ordered[0].start - origin
    tail = wall - (max(s.end for s in ordered) - origin)
    gaps = 0.0
    reach = ordered[0].end
    for span in ordered[1:]:
        if span.start > reach:
            gaps += span.start - reach
        reach = max(reach, span.end)
    return [("head", head), ("gaps", gaps), ("tail", tail)]


def _report(pass_no: int, result: dict[str, Any], spans: list[Span]) -> dict[str, float]:
    wall = result["wall"]
    origin = result["origin"]
    frames = result["frames"]
    models = [s for s in spans if s.kind == "model"]
    tools = [s for s in spans if s.kind == "tool"]
    model_busy = _merged(models)
    tool_busy = _merged(tools)
    provider_busy = _merged(spans)
    ours = wall - provider_busy

    print(f"\n--- pass {pass_no} " + "-" * 52)
    print(f"wall clock               {wall:8.2f} s")
    print(f"  model round trips      {len(models):8d}   merged {model_busy:7.2f} s")
    print(f"  tool calls             {len(tools):8d}   merged {tool_busy:7.2f} s")
    print(f"  provider busy (union)  {provider_busy:8.2f} s   {provider_busy / wall * 100:5.1f} %  CHOSEN")
    print(f"  everything else        {ours:8.2f} s   {ours / wall * 100:5.1f} %  OURS")
    for name, seconds in _ours_breakdown(spans, origin, wall):
        print(f"    {name:<20} {seconds:8.2f} s   {seconds / wall * 100:5.1f} %")

    first = frames[0]["arrivedS"] if frames else float("nan")
    readable = next(
        (f["arrivedS"] for f in frames if f.get("event") in ("progress", "token")),
        float("nan"),
    )
    last_token = max(
        (f["arrivedS"] for f in frames if f.get("event") == "token"), default=None
    )
    done = next((f["arrivedS"] for f in frames if f.get("event") == "done"), None)
    print(f"  first frame            {first:8.3f} s")
    print(f"  first readable frame   {readable:8.3f} s")
    if last_token is not None and done is not None:
        print(f"  last token -> done     {done - last_token:8.3f} s")
    print(f"  frames                 {len(frames):8d}")

    node_spans, clock = _node_spans(frames)
    print(f"  per-node wall clock — {clock}:")
    for node, start, end in node_spans:
        print(f"    {node:<28} {end - start:7.2f} s   [{start:7.2f} \u2192 {end:7.2f}]")

    print("  model round trips, in order:")
    ordered = sorted(models, key=lambda s: s.start)
    if ordered:
        print(
            "    "
            + ", ".join(f"{s.seconds:.2f}" for s in ordered)
            + f"   (span {ordered[-1].end - ordered[0].start:.2f} s)"
        )
    if tools:
        print("  tool calls:")
        for span in sorted(tools, key=lambda s: s.start):
            print(f"    {span.name:<28} {span.seconds:7.3f} s")

    head, gaps, tail = (v for _, v in _ours_breakdown(spans, origin, wall))
    return {
        "wall": wall,
        "model": model_busy,
        "tool": tool_busy,
        "ours": ours,
        "head": head,
        "gaps": gaps,
        "tail": tail,
        "calls": float(len(models)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--question", required=True)
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--model", default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument(
        "--dump",
        type=Path,
        default=None,
        help="write every frame of every pass here, for a second opinion",
    )
    args = parser.parse_args(argv)

    package = args.package.expanduser().resolve()
    _prepare_environment(package, args.env_file)

    raw = json.loads((package / "workflow.json").read_text())
    document = raw.get("document", raw)
    print(f"package     {package}")
    print(f"  nodes     {len(document.get('nodes') or [])}")
    print(f"question    {args.question[:110]}")

    _var, spans = _install_probe()

    summaries: list[dict[str, float]] = []
    with _Server() as base:
        for pass_no in range(1, args.passes + 1):
            spans.clear()
            result = asyncio.run(_drive(base, document, args.question, args.model))
            summaries.append(_report(pass_no, result, list(spans)))
            if args.dump:
                out = args.dump.expanduser()
                out.mkdir(parents=True, exist_ok=True)
                (out / f"{package.name}-pass{pass_no}.json").write_text(
                    json.dumps(result["frames"], indent=1)
                )

    print("\n=== across passes " + "=" * 46)
    for key in ("wall", "model", "tool", "ours", "head", "gaps", "tail", "calls"):
        values = [s[key] for s in summaries]
        print(
            f"  {key:<6} " + "  ".join(f"{v:8.2f}" for v in values)
            + f"   median {statistics.median(values):8.2f}"
        )
    walls = [s["wall"] for s in summaries]
    ours = [s["ours"] for s in summaries]
    print(
        "\n  ours as a share of the turn: "
        + ", ".join(f"{o / w * 100:.2f} %" for o, w in zip(ours, walls))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
