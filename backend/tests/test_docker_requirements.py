"""The Docker image installs what ``[all]`` means — resolved, and nothing more.

Pins for ``scripts/docker_requirements.py``, which exists because the
compose build died on a self-referential extra (``openstategraph[sqlite]``
inside ``[server]``) and, once past that, would have installed ``[bastion]``
against the licence exclusion recorded in the guardrails map.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from docker_requirements import flatten  # noqa: E402

PYPROJECT = ROOT / "backend" / "pyproject.toml"


def test_no_self_reference_survives() -> None:
    """pip cannot resolve ``openstategraph[...]`` from an index we are not
    published to — every self-reference must be expanded away."""
    for line in flatten(PYPROJECT):
        assert not line.startswith("openstategraph["), line


def test_the_server_extra_is_reachable_through_the_expansion() -> None:
    joined = "\n".join(flatten(PYPROJECT))
    assert "fastapi" in joined
    assert "uvicorn" in joined
    assert "langgraph-checkpoint-sqlite" in joined


def test_the_licence_exclusion_holds() -> None:
    """``bastion`` is out of ``[all]`` by recorded decision; the image must
    not re-include it through a second exclusion list of its own."""
    joined = "\n".join(flatten(PYPROJECT))
    assert "bastion" not in joined


def test_core_dependencies_lead() -> None:
    lines = flatten(PYPROJECT)
    assert any(line.startswith("langgraph") for line in lines[:4])
