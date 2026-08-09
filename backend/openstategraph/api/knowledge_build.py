"""The 'Build second brain' endpoint's orchestration (thin, injectable).

The domain lives in ``openstategraph.knowledge_builders``; this module only
sequences it — resolve a model the same way the run endpoints do, run every
builder (or one named source), fold the per-builder results into a report.
Kept separate from ``main.py`` so tests can drive ``run_build`` with a
scripted model and monkeypatch ``resolve_build_model`` without a provider.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openstategraph.knowledge import BaseKnowledge
from openstategraph.knowledge_builders import BUILDERS


class UnknownSourceError(ValueError):
    """A `source` naming no registered builder."""


def resolve_build_model(model_name: str | None, credentials: dict[str, str] | None) -> Any:
    """The same resolution chain the run endpoints use, in one place."""
    from langchain.chat_models import init_chat_model

    from openstategraph.api.model_resolution import apply_credentials, resolve_model

    apply_credentials(credentials)
    return init_chat_model(resolve_model(model_name))


def run_build(
    workflow_dir: Path,
    document: dict[str, Any],
    model: Any,
    workflows_root: Path,
    source: str | None = None,
) -> dict[str, Any]:
    """Runs the builders and reports ``{written, skipped, sources}``.

    ``source=None`` means auto: every registered builder whose ``discover``
    finds topics in this workflow runs. Written/skipped name topics (the
    normalized names double as the ``knowledge/*.md`` stems); ``sources``
    groups the same lists per builder ``source_kind``.
    """
    builders = BUILDERS
    if source is not None:
        builders = [b for b in BUILDERS if b.source_kind == source]
        if not builders:
            known = ", ".join(sorted(b.source_kind for b in BUILDERS))
            raise UnknownSourceError(f"Unknown knowledge source '{source}'. Known: {known}")

    written: list[str] = []
    skipped: list[str] = []
    sources: dict[str, dict[str, list[str]]] = {}
    for builder in builders:
        topics = builder.discover(workflow_dir, document, workflows_root)
        if not topics:
            continue
        entry = sources.setdefault(builder.source_kind, {"written": [], "skipped": []})
        for topic in topics:
            name = BaseKnowledge.normalize(topic.name)
            # Skip-check before the model call: a hand-authored doc must not
            # cost a generation it will never use.
            if builder.owns(workflow_dir, topic) and builder.write(
                workflow_dir, topic, builder.build(topic, model)
            ):
                written.append(name)
                entry["written"].append(name)
            else:
                skipped.append(name)
                entry["skipped"].append(name)
    return {"written": written, "skipped": skipped, "sources": sources}


__all__ = ["UnknownSourceError", "resolve_build_model", "run_build"]
