"""The pin reaches the frame's fields, not only the frame's name.

Framework-packaging ticket 10. `RUN_EVENTS` was published, pinned in both
languages and read by a drift test. The ~30 field names *inside* those frames
were a hand-mirror: prose in `docs/api.md`, dict literals in `streaming.py`, and
a re-declaration in `src/core/runtime/RuntimeClient.ts`, with nothing holding
the three together.

`withheld` is what that cost — emitted, documented, Python-tested, and read by
no client at all, while `api/audience.py` says the field exists precisely so a
client can tell "emptied deliberately" from "nothing happened".

`FRAME_FIELDS` is now the one declaration; `sse_responses` writes it into the
OpenAPI description, so `docs/openapi.json` publishes it and the TypeScript
side reads it off the artifact rather than off a second list. This file is the
Python half: that the declaration is not fiction, and that the guide agrees
with it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from openstategraph.api.streaming import FRAME_FIELDS, RUN_EVENTS

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "api.md"
#: Where a frame's keys are written. Two files, not one: `streaming.py` builds
#: every frame, and the `done` frame's `developer` block is assembled by
#: `audience.py` — which is the boundary owning what a customer may not see, and
#: deliberately not something `streaming.py` decides for itself.
EMITTERS = (
    ROOT / "backend" / "openstategraph" / "api" / "streaming.py",
    ROOT / "backend" / "openstategraph" / "api" / "audience.py",
)


def _guide_fields() -> dict[str, list[str]]:
    """The payload column of the guide's frame table, per event.

    Rows look like `| \\`token\\` | a chunk … | \\`node\\`, \\`namespace\\`, … |`
    — the last cell is the payload, and every field in it is backticked.
    """
    found: dict[str, list[str]] = {}
    for line in GUIDE.read_text().splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 5:
            continue
        name = re.fullmatch(r"`([a-z]+)`", cells[1])
        if not name or name.group(1) not in FRAME_FIELDS:
            continue
        # `[^`]*` after the name because the guide annotates inside the
        # backticks — `withheld: true`, `block` (`text`/`reasoning`) — and the
        # question here is whether the field is named, not how.
        found[name.group(1)] = re.findall(r"`([A-Za-z]+)[^`]*`", cells[3])
    return found


class TestTheDeclarationIsNotFiction:
    def test_every_run_event_declares_its_fields(self) -> None:
        assert set(FRAME_FIELDS) == set(RUN_EVENTS)

    def test_every_declared_field_is_a_key_this_module_writes(self) -> None:
        """The control that stops `FRAME_FIELDS` becoming a wish list. A field
        nobody emits published as part of the contract is the same defect as a
        field emitted and published to nobody, pointed the other way."""
        source = "\n".join(path.read_text() for path in EMITTERS)
        emitted = set(re.findall(r'"([A-Za-z]+)":', source))
        declared = {field for fields in FRAME_FIELDS.values() for field in fields}

        assert declared <= emitted, sorted(declared - emitted)

    def test_the_extractor_is_reading_something(self) -> None:
        assert len(_guide_fields()) == len(RUN_EVENTS)


class TestTheGuideAndTheEmitterAgree:
    def test_each_frame_carries_what_the_guide_says_it_carries(self) -> None:
        """`docs/api.md` is what a stranger builds a client from, and it is
        prose — so it is the leg most able to drift and least able to fail."""
        guide = _guide_fields()

        for name, fields in FRAME_FIELDS.items():
            assert set(guide[name]) >= set(fields), (
                f"the guide's `{name}` row does not mention "
                f"{sorted(set(fields) - set(guide[name]))} — either the emitter gained "
                f"a field the page never told anyone about, or the page lost one."
            )


class TestTheContractPublishesThem:
    @staticmethod
    def _published() -> dict[str, list[str]]:
        document = json.loads((ROOT / "docs" / "openapi.json").read_text())
        description = document["paths"]["/api/runs/stream"]["post"]["responses"]["200"][
            "description"
        ]
        sentence = re.search(r"Frame fields: (.*?)\. ", description, re.S)
        assert sentence, "docs/openapi.json no longer publishes the frame fields"
        return {
            name: re.findall(r"`([A-Za-z]+)`", fields)
            for name, fields in re.findall(r"`([a-z]+)`: ([^;]+)", sentence.group(1))
        }

    def test_the_committed_snapshot_carries_every_frame(self) -> None:
        assert self._published() == {name: list(f) for name, f in FRAME_FIELDS.items()}

    def test_resume_publishes_the_same_vocabulary(self) -> None:
        document = json.loads((ROOT / "docs" / "openapi.json").read_text())
        of = lambda path: document["paths"][path]["post"]["responses"]["200"]["description"]  # noqa: E731

        assert re.search(r"Frame fields: .*", of("/api/runs/stream"), re.S) is not None
        assert of("/api/runs/stream").split("\n\n", 1)[1] == of("/api/runs/resume").split(
            "\n\n", 1
        )[1]

    def test_an_endpoint_with_no_run_frames_publishes_no_field_list(self) -> None:
        """`GET /api/events` carries one catalogue hint. Inventing an entry so
        the sentence is never blank would be the mirror this removes."""
        document = json.loads((ROOT / "docs" / "openapi.json").read_text())

        assert "Frame fields:" not in document["paths"]["/api/events"]["get"]["responses"]["200"][
            "description"
        ]
