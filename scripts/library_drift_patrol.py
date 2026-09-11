#!/usr/bin/env python3
"""Run the library-contract corpus and file each failure as a card.

**What this answers that nothing else does.** Three questions about the vendor
are easy to confuse:

| Question | Answered by | When |
| --- | --- | --- |
| Does our code still hold against the installed library? | `-m library_contract`, in CI | every push |
| Has the library moved under us? | **this script** | daily |
| Did their prose change enough to move a design verdict? | the docs-watch | weekly |

The middle row is this one, and it exists because the third could not have
found the defect that created the map. `langchain-drift-watch` 01 was a timeout
passed to `add_node` for a synchronous body — refused by LangGraph since 1.2,
pinned in one of our own tests, and contradicted by two other places in this
repository for a whole release. **Nothing had changed.** A watcher pointed at
the vendor's documentation is structurally blind to that, because the drift was
between two of our own files with the library's rule as referee.

So the signal here is not a changed page and not a changed version string. It
is a red test, run against a dependency resolve with **no lockfile**, which is
what a person installing today would get.

**Why the corpus is a pytest marker.** A library fact belongs beside the code
that depends on it, so these tests are spread across the suite deliberately and
`-m library_contract` is the only thing that gathers them. Extending the corpus
is marking a test; it never means editing this file. The cost of that choice is
that a renamed marker would make the patrol vacuously green, which is why
`test_the_drift_corpus_is_not_empty` asserts a floor separately.

**Why it writes a card rather than a gap report.** `file_gap_report` is the
keyless, rate-limited, public door for a *stranger's* install reporting a
platform gap in a fixed vocabulary. A drift finding is none of those — it is
ours, it has a credential, and nobody hit it. Forcing it through would cost a
new gap kind, a regenerated contract and an Edge Function redeploy to reach the
same `public.cards` row that `file_card` writes directly. Same board either
way.

Not shipped in the wheel: this is maintainers' tooling, beside
`ticket_ledger.py`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from typing import Any, Sequence

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The board a drift card belongs on — the shared one, not this laptop's.
TEAM_BOARD = "osgEngineering"

#: The variable that decides whether there is a shared board at all.
KANBAN_URL_ENV = "OPENSTATEGRAPH_KANBAN_URL"

#: Distributions whose versions make a finding reproducible. A claim of the
#: form "measured on the installed version" is worthless without them.
WATCHED = ("langgraph", "langchain", "langchain-core", "deepagents")

EXIT_OK = 0
EXIT_FOUND = 1
EXIT_COULD_NOT_FILE = 2


def installed_versions(names: Sequence[str] = WATCHED) -> dict[str, str]:
    """What is actually importable here, read from the metadata."""
    from importlib.metadata import PackageNotFoundError, version

    found: dict[str, str] = {}
    for name in names:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            continue
    return found


def git_sha() -> str:
    """The tree this ran against, short. Empty when git cannot answer."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return done.stdout.strip()


def run_corpus(report: pathlib.Path) -> int:
    """Run exactly the marked tests, writing a junit report. Returns pytest's code."""
    done = subprocess.run(
        [
            sys.executable, "-m", "pytest", "backend/tests",
            "-m", "library_contract", "-q", "-p", "no:randomly",
            f"--junitxml={report}",
        ],
        cwd=REPO_ROOT,
    )
    return done.returncode


def cards_for(
    report: pathlib.Path,
    *,
    versions: dict[str, str],
    sha: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """One card per failed test, or an empty list.

    The `task_id` is a hash of the test's node id, so the same failure on two
    consecutive days is the same card rather than two. Twelve hex characters,
    matching `patrol.refusal_task_id`'s width and for its reason: long enough
    not to collide, short enough to read in a board column.
    """
    tree = ElementTree.parse(report)
    stamp = ", ".join(f"{name}=={value}" for name, value in sorted(versions.items()))

    cards: list[dict[str, Any]] = []
    for case in tree.iter("testcase"):
        failures = list(case.findall("failure")) + list(case.findall("error"))
        if not failures:
            continue
        node_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        summary = (failures[0].get("message") or "").strip().splitlines()
        first_line = summary[0] if summary else "the assertion gave no message"

        digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:12]
        reason = first_line
        if stamp:
            reason += f" — measured against {stamp}"
        if sha:
            reason += f", tree {sha}"

        cards.append(
            {
                "task_id": f"{project_id}:drift:{digest}",
                "board": TEAM_BOARD,
                "kind": "bug",
                "category": "bug",
                "title": f"A library-contract test is red: {case.get('name', node_id)}",
                "priority": "high",
                "area": "backend",
                "priority_reason": reason,
                "story": (
                    f"`{node_id}` asserts this codebase against the installed "
                    "langgraph/langchain and is failing. Judge it before fixing: "
                    "either the vendor moved (confirm against their current docs, "
                    "file a ticket, and never edit the pin to make it pass), or "
                    "our code contradicts a fact we had already pinned."
                ),
                "done_when": (
                    "The test is green for a reason recorded in a ticket, not by "
                    "editing the assertion."
                ),
                # Ours, never a platform gap somebody hit — the report door
                # would refuse it by name, and rightly.
                "gap_evidence": "",
            }
        )
    return cards


def file_cards(store: Any, cards: Sequence[dict[str, Any]]) -> tuple[int, int]:
    """File what is new, skip what is already there. Returns `(filed, skipped)`.

    `read_card` first, exactly as `patrol.run_patrol` does: a patrol that
    refiled every morning would bury the board it exists to inform.
    """
    filed = skipped = 0
    for card in cards:
        try:
            store.read_card(card["task_id"])
        except Exception:
            store.file_card(**card)
            filed += 1
        else:
            skipped += 1
    return filed, skipped


def _project_id() -> str:
    """This installation's minted id, or a name that says it is missing.

    `active_config()` takes no argument and is memoised — it finds the config
    by walking up from the working directory, which is why this script says to
    run it from the repository root. A missing id is not fatal: the task id
    only has to be stable, and `unknown` is stable.
    """
    from openstategraph.config_file import active_config

    config = active_config()
    return str(getattr(config, "project_id", None) or "unknown")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be filed and write nothing",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="skip the test run (for checking the credential alone)",
    )
    parser.add_argument("--junit", type=pathlib.Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Checked before anything expensive. A patrol that cannot file what it
    # finds should not run at all: this repository already has one scheduled
    # job that fails every week and is read as one that passes.
    if not args.dry_run and not os.environ.get(KANBAN_URL_ENV, "").strip():
        print(
            f"{KANBAN_URL_ENV} is not set, so a finding could not be filed anywhere. "
            "Set it to the team board's URL, or pass --dry-run to see what would "
            "be filed.",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_COULD_NOT_FILE)

    versions = installed_versions()
    for name, value in sorted(versions.items()):
        print(f"{name}=={value}")

    report = args.junit or (REPO_ROOT / ".drift-report.xml")
    if not args.no_run:
        run_corpus(report)
    if not report.exists():
        print("no junit report was produced", file=sys.stderr)
        raise SystemExit(EXIT_COULD_NOT_FILE)

    cards = cards_for(
        report, versions=versions, sha=git_sha(), project_id=_project_id()
    )
    print(f"{len(cards)} failure(s)")

    if not cards:
        return EXIT_OK

    for card in cards:
        print(f"  {card['task_id']}  {card['title']}")
        print(f"    {card['priority_reason']}")

    if args.dry_run:
        print("(dry run — nothing filed)")
        return EXIT_FOUND

    from openstategraph.kanban_store import open_kanban_store

    try:
        store = open_kanban_store()
        filed, skipped = file_cards(store, cards)
    except Exception as exc:  # noqa: BLE001 — the exit code is the point
        print(f"could not file: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_COULD_NOT_FILE) from exc

    print(f"filed {filed}, skipped {skipped} already on the board")
    return EXIT_FOUND


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
