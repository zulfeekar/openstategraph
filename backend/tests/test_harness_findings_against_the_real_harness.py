"""`launch-readiness/144`: the harness's shapes, read off the harness itself.

`tests/test_tool_findings.py` pins the *readers* against captured strings.
This file pins the **capture** — it drives the installed
`deepagents==0.7.5`'s own `FilesystemMiddleware` tools against a real
`FilesystemBackend` and feeds their actual results through
`summarise_tool_result`.

That distinction is the whole point of the ticket's "Watch for":

> The shapes are `deepagents`', not a server's. `143`'s table only carries
> keys somebody has read off a live result, on purpose. These need the same
> treatment against the installed `deepagents==0.7.5` — read the return of
> `FilesystemBackend.read`/`grep`/`glob`, do not guess.

A guessed shape resolves to nothing, produces no line, and is
indistinguishable from a tool with nothing to report — so a fixture that has
drifted from the library would leave the panel silent again with this
project's own suite green. This file is what fails on that day.

The backend is the same one `abc/deep_tier_offload.py` builds
(`virtual_mode=True`), so what is exercised here is the surface a
`DeepAgentNode` actually has.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.tools import ToolRuntime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.abc.tool_findings import SENTENCE_SHAPES, summarise_tool_result  # noqa: E402


@pytest.fixture
def harness(tmp_path: Path) -> Any:
    """The harness's own file tools, over a small tree with the shapes that matter."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "offload" / "mcp_list_lenses").mkdir(parents=True)
    (tmp_path / "a.txt").write_text("hello\nworld\nalpha beta\n")
    (tmp_path / "sub" / "b.txt").write_text("alpha\n" * 10)
    (tmp_path / "long.txt").write_text("".join(f"line {i}\n" for i in range(250)))
    (tmp_path / "empty.txt").write_text("")
    # What `launch-readiness/102` writes and the agent reads back: one line.
    (tmp_path / "offload" / "mcp_list_lenses" / "call_eeR8.txt").write_text(
        json.dumps({"ok": True, "data": {"lenses": [{"lens_id": f"l{i}"} for i in range(15)]}})
    )
    backend = FilesystemBackend(root_dir=os.fspath(tmp_path), virtual_mode=True)
    tools = {tool.name: tool for tool in FilesystemMiddleware(backend=backend).tools}
    runtime = ToolRuntime(
        state={"messages": []},
        context=None,
        config={},
        stream_writer=lambda *_a, **_k: None,
        tool_call_id="call_abc123",
        store=None,
    )

    def call(name: str, **args: Any) -> str | None:
        result = tools[name].func(runtime=runtime, **args)
        return summarise_tool_result(name, getattr(result, "content", result))

    return call


class TestTheFindingIsReadOffTheInstalledHarness:
    def test_a_short_read_counts_its_lines(self, harness: Any) -> None:
        assert harness("read_file", file_path="/a.txt") == "Read 3 lines."

    def test_a_long_read_says_it_is_a_window_onto_a_longer_file(self, harness: Any) -> None:
        # `deepagents`' own `DEFAULT_READ_LIMIT` is 100. Whether that is the
        # whole file is exactly what `144` asked the line to carry.
        assert harness("read_file", file_path="/long.txt") == "Read 100 of 250 lines in the file."

    def test_an_offloaded_payload_read_back_is_measured_in_characters(self, harness: Any) -> None:
        line = harness("read_file", file_path="/offload/mcp_list_lenses/call_eeR8.txt")
        assert line is not None and line.endswith("characters on one line.")
        assert "1 line" not in line

    def test_an_empty_file_says_so(self, harness: Any) -> None:
        assert harness("read_file", file_path="/empty.txt") == "That file is empty."

    def test_a_missing_file_is_a_failure_not_a_silence(self, harness: Any) -> None:
        assert harness("read_file", file_path="/nope.txt") == "That did not work."

    def test_a_listing_counts_what_the_folder_holds(self, harness: Any) -> None:
        assert harness("ls", path="/") == "Found 5 files and folders."

    def test_a_glob_counts_its_matches(self, harness: Any) -> None:
        assert harness("glob", pattern="**/*.txt") == "Found 5 matching files."
        assert harness("glob", pattern="**/*.nope") == "No matching files."

    def test_each_grep_output_mode_is_counted_by_what_it_carries(self, harness: Any) -> None:
        assert harness("grep", pattern="alpha") == "Found matches in 2 files."
        assert harness("grep", pattern="alpha", output_mode="count") == "Found 11 matches in 2 files."
        assert (
            harness("grep", pattern="alpha", output_mode="content") == "Found 11 matches in 2 files."
        )
        assert harness("grep", pattern="zzznothing") == "No matches found."

    def test_a_write_and_an_edit_report_what_they_did(self, harness: Any) -> None:
        assert harness("write_file", file_path="/n.txt", content="a\nb\n") == "Saved the file."
        assert (
            harness("edit_file", file_path="/a.txt", old_string="hello", new_string="HI")
            == "Changed 1 place in the file."
        )


class TestNothingTheHarnessSaysLeaksThroughTheLine:
    def test_no_real_result_puts_a_path_in_the_sentence(self, harness: Any) -> None:
        calls = [
            ("read_file", {"file_path": "/a.txt"}),
            ("read_file", {"file_path": "/offload/mcp_list_lenses/call_eeR8.txt"}),
            ("read_file", {"file_path": "/nope.txt"}),
            ("ls", {"path": "/"}),
            ("glob", {"pattern": "**/*.txt"}),
            ("grep", {"pattern": "alpha"}),
            ("write_file", {"file_path": "/n.txt", "content": "a\n"}),
        ]
        for name, args in calls:
            line = harness(name, **args) or ""
            assert "/" not in line, (name, line)
            assert ".txt" not in line, (name, line)
            assert "offload" not in line, (name, line)

    def test_every_line_a_real_call_produces_is_a_published_shape(self, harness: Any) -> None:
        calls = [
            ("read_file", {"file_path": "/a.txt"}),
            ("read_file", {"file_path": "/long.txt"}),
            ("read_file", {"file_path": "/empty.txt"}),
            ("read_file", {"file_path": "/nope.txt"}),
            ("ls", {"path": "/"}),
            ("glob", {"pattern": "**/*.txt"}),
            ("glob", {"pattern": "**/*.nope"}),
            ("grep", {"pattern": "alpha"}),
            ("grep", {"pattern": "alpha", "output_mode": "count"}),
            ("grep", {"pattern": "alpha", "output_mode": "content"}),
            ("grep", {"pattern": "zzznothing"}),
            ("write_file", {"file_path": "/n.txt", "content": "a\n"}),
            ("edit_file", {"file_path": "/a.txt", "old_string": "hello", "new_string": "HI"}),
        ]
        for name, args in calls:
            line = harness(name, **args)
            assert line, (name, args)
            assert re.sub(r"\d+", "#", line) in SENTENCE_SHAPES, (name, line)
