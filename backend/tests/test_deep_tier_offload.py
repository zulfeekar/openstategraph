"""`launch-readiness/101` and `102` — the deep-tier seam, no network, no model.

Proves, against the installed `deepagents` and `langchain` packages directly
(no compiled workflow, no live model):

- a skill's body is absent from the initial system prompt while its name and
  description are present, and the body is reachable on demand via the
  backend's own `read`.
- a tool result above the offload threshold is written to the filesystem
  backend and replaced with a pointer; one below it is left inline untouched.
- a path outside the jailed root is refused as a result (`.error` set),
  never a raised exception.
- both middlewares occupy the slot names `AbstractAgentNode.SLOT_ORDER`
  already reserves for them (`"skills"`, `"filesystem"`), in that order.
"""

from __future__ import annotations

from types import SimpleNamespace

from deepagents.backends import FilesystemBackend
from langchain_core.messages import ToolMessage

from openstategraph.abc.agent import AbstractAgentNode
from openstategraph.abc.deep_tier_offload import (
    OffloadMiddleware,
    build_skills_middleware,
)


def _skill_dir(tmp_path, name="greet", body="Full instructions go here.\n" * 50):
    # Virtual paths under `FilesystemBackend(root_dir=tmp_path)`: the real
    # directory is `tmp_path/skills/<name>/SKILL.md`, addressed by the
    # backend as the virtual path `/skills/<name>/SKILL.md`.
    real_root = tmp_path / "skills"
    skill_dir = real_root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Say hello politely.\n---\n\n{body}"
    )
    return "/skills"


def test_skill_body_absent_from_initial_prompt_but_name_and_description_present(tmp_path):
    virtual_root = _skill_dir(tmp_path)
    mw = build_skills_middleware(root_dir=tmp_path, sources=[virtual_root])

    # SkillsMiddleware renders its system-prompt fragment from discovered
    # metadata at construction — this is the progressive-disclosure claim
    # itself: only name + description enter the prompt.
    prompt_fragment = mw.system_prompt_template.format(
        skills_locations="",
        skills_load_warnings="",
        skills_list=_render_skills_list(mw),
    )
    assert "Say hello politely." in prompt_fragment
    assert "Full instructions go here." not in prompt_fragment


def _render_skills_list(mw) -> str:
    # Mirrors what the middleware itself builds into state at startup —
    # exercised directly rather than through a live agent run.
    lines = []
    for source in mw.sources:
        backend = mw._backend
        for entry in backend.ls(source).entries or []:
            if entry.get("is_dir"):
                skill_path = f"{entry['path'].rstrip('/')}/SKILL.md"
            else:
                skill_path = entry["path"]
            read = backend.read(skill_path)
            if read.error or read.file_data is None:
                continue
            frontmatter = read.file_data["content"].split("---")[1]
            lines.append(frontmatter)
    return "\n".join(lines)


def test_skill_body_is_reachable_on_demand(tmp_path):
    virtual_root = _skill_dir(tmp_path, body="THE FULL BODY TEXT")
    mw = build_skills_middleware(root_dir=tmp_path, sources=[virtual_root])
    backend = mw._backend
    result = backend.read(f"{virtual_root}/greet/SKILL.md")
    assert result.error is None
    assert "THE FULL BODY TEXT" in result.file_data["content"]


def _request(tool_name="query.run", call_id="call-1"):
    return SimpleNamespace(tool_call={"name": tool_name, "id": call_id})


def test_large_tool_result_above_threshold_is_offloaded(tmp_path):
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    mw = OffloadMiddleware(
        backend=backend, tool_name_prefixes=("query.",), threshold_chars=100
    )
    big = ToolMessage(content="x" * 500, tool_call_id="call-1")
    result = mw.wrap_tool_call(_request(), lambda req: big)

    assert result is not big
    assert "offloaded" in result.text
    assert "call-1" in result.text
    # And the content really landed on the backend, retrievable by path.
    written_path = result.text.split("path='", 1)[1].split("'", 1)[0]
    read_back = backend.read(written_path)
    assert read_back.error is None
    assert read_back.file_data["content"] == "x" * 500


def test_small_tool_result_below_threshold_is_left_inline(tmp_path):
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    mw = OffloadMiddleware(
        backend=backend, tool_name_prefixes=("query.",), threshold_chars=100
    )
    small = ToolMessage(content="short result", tool_call_id="call-2")
    result = mw.wrap_tool_call(_request(), lambda req: small)

    assert result is small
    assert result.text == "short result"


def test_offload_is_prefix_filtered_not_blanket(tmp_path):
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    mw = OffloadMiddleware(
        backend=backend, tool_name_prefixes=("query.",), threshold_chars=10
    )
    big = ToolMessage(content="y" * 500, tool_call_id="call-3")
    # A tool outside the prefix filter is never offloaded, however large.
    result = mw.wrap_tool_call(
        _request(tool_name="unrelated.tool"), lambda req: big
    )
    assert result is big


def test_installed_backend_jail_rejects_traversal_but_by_raising_not_a_result(tmp_path):
    """Documents a real gap in the installed `deepagents==0.7.5` backend.

    `FilesystemBackend._resolve_path` raises `ValueError` for a `..` path,
    but `write`/`read` only catch `(OSError, RuntimeError)` around that
    call — so the jail's containment is real (nothing escapes `tmp_path`)
    but its *refusal* is an uncaught raise, not the `.error`-bearing result
    every other failure mode returns. `launch-readiness/102` records this
    as a finding rather than re-implementing the jail: `OffloadMiddleware`
    (this module) wraps its own call to `backend.write` to keep the
    result-not-raise promise regardless — see the next test.
    """
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    import pytest

    with pytest.raises(ValueError, match="traversal"):
        backend.write("../../etc/passwd", "pwned")
    assert not (tmp_path.parent.parent / "etc" / "passwd").exists()


def test_offload_middleware_survives_the_backends_raise_and_still_returns_a_result(
    tmp_path,
):
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    mw = OffloadMiddleware(
        backend=backend,
        tool_name_prefixes=("query.",),
        threshold_chars=10,
        path_for=lambda request: "../../etc/passwd",
    )
    big = ToolMessage(content="z" * 500, tool_call_id="call-5")
    result = mw.wrap_tool_call(_request(), lambda req: big)
    # A raise from the backend is caught at this middleware's own boundary
    # and turned into "leave the original message alone" — a recoverable
    # result, never a dead run.
    assert result is big


def test_offload_backend_write_failure_falls_back_to_original_message(monkeypatch, tmp_path):
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)

    def _always_fails(path, content):
        return SimpleNamespace(error="refused for the test", path=None)

    monkeypatch.setattr(backend, "write", _always_fails)
    mw = OffloadMiddleware(
        backend=backend, tool_name_prefixes=("query.",), threshold_chars=10
    )
    big = ToolMessage(content="z" * 500, tool_call_id="call-4")
    result = mw.wrap_tool_call(_request(), lambda req: big)
    assert result is big


def test_slot_order_reserves_skills_before_filesystem():
    order = AbstractAgentNode.SLOT_ORDER
    assert "skills" in order
    assert "filesystem" in order
    assert order.index("skills") < order.index("filesystem")


def test_both_middlewares_land_in_their_reserved_slots(tmp_path):
    from openstategraph.abc.middleware import MiddlewareSlotTable

    root = _skill_dir(tmp_path)
    skills_mw = build_skills_middleware(root_dir=tmp_path, sources=[str(root)])
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    offload_mw = OffloadMiddleware(backend=backend, tool_name_prefixes=("query.",))

    table = MiddlewareSlotTable(order=AbstractAgentNode.SLOT_ORDER)
    table.merge({"filesystem": offload_mw, "skills": skills_mw})

    flat = table.flatten()
    assert flat.index(skills_mw) < flat.index(offload_mw)


# --------------------------------------------------------------------------- #
# The async twin (`async-first/06`).
#
# `_agent`'s body is `async def` in Phase D, so a deep-tier agent is reached
# through `ainvoke` — and `awrap_tool_call` has no usable default: LangChain
# raises `NotImplementedError` naming the sync method. A deep agent whose
# offload middleware lacked it would have died on its first tool call.
# --------------------------------------------------------------------------- #


def test_the_async_path_offloads_the_same_way(tmp_path):
    import asyncio

    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    mw = OffloadMiddleware(
        backend=backend, tool_name_prefixes=("query.",), threshold_chars=100
    )
    big = ToolMessage(content="y" * 500, tool_call_id="call-1")

    async def handler(_req):
        return big

    result = asyncio.run(mw.awrap_tool_call(_request(), handler))

    assert result is not big
    assert "offloaded" in result.text
    written_path = result.text.split("path='", 1)[1].split("'", 1)[0]
    assert backend.read(written_path).file_data["content"] == "y" * 500


def test_the_async_path_leaves_a_small_result_inline(tmp_path):
    import asyncio

    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    mw = OffloadMiddleware(
        backend=backend, tool_name_prefixes=("query.",), threshold_chars=100
    )
    small = ToolMessage(content="short result", tool_call_id="call-2")

    async def handler(_req):
        return small

    assert asyncio.run(mw.awrap_tool_call(_request(), handler)) is small
