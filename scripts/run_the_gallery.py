#!/usr/bin/env python3
"""Ask every gallery package a question, twice, and report what came back.

`launch-readiness/188`. The gallery is well covered at the document layer —
twenty-two of the twenty-four examples ship `tests/`, and those tests assert
the document and the wiring, "neither of them needing a model". It was
uncovered at the *live-run* layer, which is where `launch-readiness/185` lives:
before this script, twenty-three of the twenty-four packages had never been
asked a question.

A **hand-run driver, committed**, not a CI job — CI cannot call a model.
`scripts/run_stress_workload.py`, `scripts/measure_setup_path.py` and
`scripts/measure_turn.py` are the precedent, and the reason is theirs: so the
next person re-measures instead of re-arguing.

The questions are `scripts/gallery_questions.json`, which carries the argument
for why they are a committed per-package list rather than one generic prompt.

**Run each package more than once.** The default is two laps and the default is
load-bearing: the most valuable finding of 2026-08-27 was not a latency, it was
*"three runs, three different answers"*. A single lap of this sweep can say a
package works when what it means is that it worked once.

Spend alert: this drives every package in the gallery against a real model.
The full sweep is a few hundred model calls; `youtube-trend-digest` also makes
one paid Anthropic call per lap.

Usage:

    python3 scripts/run_the_gallery.py                 # everything, two laps
    python3 scripts/run_the_gallery.py --laps 1
    python3 scripts/run_the_gallery.py --package sql-qa --package chinook-assistant
    python3 scripts/run_the_gallery.py --skip-network  # leave the web ones out
    python3 scripts/run_the_gallery.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
EXAMPLES = BACKEND / "openstategraph" / "examples"
WORKFLOWS = REPO / "workflows"
QUESTIONS = Path(__file__).resolve().parent / "gallery_questions.json"

#: The one thing a run can produce that looks like an answer and is not: the
#: grader's own sentence when the attempt cap ran out with nothing to hand on.
#: `compile/nodes/grader.py` writes it; matching its head rather than the whole
#: string keeps the two spellings (attempt cap, step budget) in one bucket.
REFUSAL_HEAD = "I could not produce an answer"


def prepare_environment(workflows_root: Path, env_from: Path | None = None) -> None:
    """The three fixes without which every live run fails silently.

    `CLAUDE.md`, live-run env — and the failure they prevent is the expensive
    one, because a misrouted run does not error, it produces a worse answer
    from a different model or no answer at all.

    1. Load a `.env`. Scripts read none on their own.
    2. Drop `OLLAMA_HOST` **and** `OLLAMA_ENDPOINT`. Both are commonly set and
       both misroute to a local daemon; only with both gone does
       `https://ollama.com` apply, and Ollama means Ollama **cloud**.
    3. `OPENSTATEGRAPH_WORKFLOWS_ROOT`, absolute, at the packages' directory —
       `sql-qa` names `sql-qa/data/Chinook_Sqlite.sqlite` and resolves it under
       `workflows_root()`. The sweep spans **two** roots, so `run_lap` re-points
       it per package; this is only the floor.
    """
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from openstategraph.dotenv import load_env_file

    load_env_file(env_from or Path.cwd())
    os.environ.pop("OLLAMA_HOST", None)
    os.environ.pop("OLLAMA_ENDPOINT", None)
    os.environ.setdefault("OPENSTATEGRAPH_MODEL", "ollama:gpt-oss:120b-cloud")
    os.environ["OPENSTATEGRAPH_WORKFLOWS_ROOT"] = str(workflows_root.resolve())


@dataclass
class Lap:
    """What one run of one package produced."""

    status: str = "errored"
    duration_s: float = 0.0
    attempts: int = 0
    answer_chars: int = 0
    #: node id -> branch, the graph's own record of every routing decision
    #: this run took. A grader's verdict is in here under its node id.
    decisions: dict[str, str] = field(default_factory=dict)
    #: Nodes whose published output is blank. This is `185`'s signal, and it
    #: is why the sweep reads `outputs` rather than only the answer: `answer`
    #: has a LATEST_NONEMPTY reducer, so an empty node output can be masked at
    #: the answer and still be the reason a grader saw nothing.
    silent_nodes: list[str] = field(default_factory=list)
    #: Nodes LangGraph's retry policy re-ran because they raised.
    retried_nodes: list[str] = field(default_factory=list)
    error: str = ""

    def cell(self) -> str:
        marks = ""
        if self.retried_nodes:
            marks += f" retry:{','.join(self.retried_nodes)}"
        if self.silent_nodes:
            marks += f" silent:{','.join(self.silent_nodes)}"
        return f"{self.status:<9} {self.duration_s:6.1f}s a={self.attempts}{marks}"


def classify(result: Any) -> str:
    """One of: answered / refused / paused / empty.

    `refused` is separated from `answered` on purpose. It is a legitimate
    outcome for `budget-exhaustion`, whose rubric cannot be satisfied, and a
    defect for everything else — and it reads as a perfectly healthy run
    everywhere else in the system, which is how `185` came to be filed against
    a workflow no failure channel complained about.
    """
    if getattr(result, "pause", None) is not None:
        return "paused"
    text = str(result)
    if not text.strip():
        return "empty"
    if text.lstrip().startswith(REFUSAL_HEAD):
        return "refused"
    return "answered"


def silent_nodes(result: Any) -> list[str]:
    """Nodes that published nothing. See `Lap.silent_nodes` for why."""
    return sorted(
        node
        for node, value in (getattr(result, "outputs", {}) or {}).items()
        if not str(value or "").strip()
    )


def retried_nodes(result: Any) -> list[str]:
    """Nodes named by a recovered-retry warning.

    Read out of the warning text rather than from state, because the warning
    is the only published surface for it — `retry_warnings` in
    `compile/workflow_compiler.py` is deliberately on `.warnings` and not on
    `.failures`, so a transient provider hiccup does not fail a build.
    """
    found = []
    for warning in getattr(result, "warnings", []) or []:
        if "failed and was retried" in warning:
            head, _, rest = warning.partition('"')
            name, _, _ = rest.partition('"')
            if name:
                found.append(name)
    return sorted(set(found))


def run_lap(package_dir: Path, question: str, model: str, thread: str | None) -> Lap:
    from openstategraph import load_workflow
    from openstategraph.errors import RunProducedNothing

    lap = Lap()
    started = time.monotonic()
    workflow = None
    # Per package, not once for the sweep: the two roots are real directories
    # with real dependants. `sql-qa` resolves `sql-qa/data/Chinook_Sqlite.sqlite`
    # under `workflows_root()`, and `delegate-by-mount` mounts `sql-qa` and
    # `web-research-digest` by slug — both of which are only findable when the
    # root is the one this package actually lives in.
    os.environ["OPENSTATEGRAPH_WORKFLOWS_ROOT"] = str(package_dir.parent.resolve())
    try:
        workflow = load_workflow(package_dir, model=model)
        result = workflow.ask(question, thread_id=thread)
        lap.status = classify(result)
        lap.attempts = int(getattr(result, "attempts", 0) or 0)
        lap.answer_chars = len(str(result))
        lap.decisions = dict(getattr(result, "decisions", {}) or {})
        lap.silent_nodes = silent_nodes(result)
        lap.retried_nodes = retried_nodes(result)
    except RunProducedNothing as exc:
        # The run finished and produced nothing, with a reason. That is a
        # distinct outcome from a crash and the whole `RunResult` rides on the
        # error, so nothing a reader could have used is lost by the raise.
        lap.status = "empty"
        lap.error = str(exc)
        carried = getattr(exc, "result", None)
        if carried is not None:
            lap.attempts = int(getattr(carried, "attempts", 0) or 0)
            lap.decisions = dict(getattr(carried, "decisions", {}) or {})
            lap.silent_nodes = silent_nodes(carried)
            lap.retried_nodes = retried_nodes(carried)
    except Exception as exc:  # noqa: BLE001 - the sweep reports, never raises
        lap.status = "errored"
        lap.error = f"{type(exc).__name__}: {exc}"
    finally:
        lap.duration_s = time.monotonic() - started
        if workflow is not None:
            try:
                workflow.close()
            except Exception:  # noqa: BLE001
                pass
    return lap


def locate(slug: str) -> Path | None:
    """`workflows/` first, then the installed examples.

    Order matters and follows the product's own: a package in the user's
    workflows root is the one the editor opens and the one `?w=<slug>` names,
    and four slugs exist in both places.
    """
    for root in (WORKFLOWS, EXAMPLES):
        candidate = root / slug
        if (candidate / "workflow.json").is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="append", dest="packages")
    parser.add_argument("--laps", type=int, default=2)
    parser.add_argument("--model", default=None)
    parser.add_argument("--skip-network", action="store_true")
    parser.add_argument("--skip-paid", action="store_true")
    parser.add_argument("--json", dest="json_out", default=None)
    parser.add_argument(
        "--env-from",
        default=None,
        help="Directory to look for a .env in (default: cwd).",
    )
    args = parser.parse_args(argv)

    prepare_environment(
        WORKFLOWS, Path(args.env_from) if args.env_from else None
    )
    model = args.model or os.environ["OPENSTATEGRAPH_MODEL"]

    spec = json.loads(QUESTIONS.read_text(encoding="utf-8"))["packages"]
    names = args.packages or list(spec)

    report: dict[str, Any] = {"model": model, "laps": args.laps, "packages": {}}
    print(f"\nGallery sweep — {len(names)} entries, {args.laps} lap(s), model {model}\n")
    print(f"{'package':<32} {'expect':<9} {'laps'}")
    print("-" * 100)

    for name in names:
        entry = spec.get(name)
        if entry is None:
            print(f"{name:<32} {'?':<9} not in gallery_questions.json")
            continue
        if args.skip_network and entry.get("network"):
            print(f"{name:<32} {entry['expect']:<9} skipped (network)")
            continue
        if args.skip_paid and entry.get("paid"):
            print(f"{name:<32} {entry['expect']:<9} skipped (paid)")
            continue
        package_dir = locate(entry.get("package", name))
        if package_dir is None:
            print(f"{name:<32} {entry['expect']:<9} NO SUCH PACKAGE")
            continue

        laps: list[Lap] = []
        for _ in range(args.laps):
            try:
                laps.append(
                    run_lap(package_dir, entry["question"], model, entry.get("thread"))
                )
            except KeyboardInterrupt:
                print("\ninterrupted")
                return 130
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                laps.append(Lap(status="errored", error="driver failure"))

        statuses = {lap.status for lap in laps}
        agreed = "  " if len(statuses) == 1 else "!!"
        met = all(lap.status == entry["expect"] for lap in laps)
        print(
            f"{name:<32} {entry['expect']:<9} {agreed} "
            + " | ".join(lap.cell() for lap in laps)
            + ("" if met else "   <-- not what this package promises")
        )
        report["packages"][name] = {
            "expect": entry["expect"],
            "question": entry["question"],
            "package_dir": str(package_dir),
            "laps": [lap.__dict__ for lap in laps],
            "agreed_across_laps": len(statuses) == 1,
            "met_expectation": met,
        }

    ran = report["packages"].values()
    print("-" * 100)
    print(
        f"{sum(1 for r in ran if r['met_expectation'])}/{len(list(ran))} met their "
        f"expectation; {sum(1 for r in ran if not r['agreed_across_laps'])} disagreed "
        "between laps"
    )
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        print("wrote", args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
