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
from openstategraph.knowledge_explorer import AgenticKnowledgeBuilder  # registers agentic builders


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
    instruction: str | None = None,
) -> dict[str, Any]:
    """Runs the builders; reports ``{written, skipped, collisions, warnings, sources}``.

    ``source=None`` means auto: every registered builder whose ``discover``
    finds topics in this workflow runs. Written/skipped name topics (the
    normalized names double as the ``knowledge/*.md`` stems); ``sources``
    groups the same lists per builder ``source_kind``. Two additive fields
    keep the original shape backward compatible:

    - ``warnings`` — sources a builder recognized but could not open (e.g. a
      postgres ref with no driver installed): reported, never a crash.
    - ``collisions`` (invariant 5) — a topic whose on-disk marker names a
      *different* builder is refused and reported here, never
      last-write-wins. Since builders run in registration order and every
      write stamps its owner, an in-run cross-builder collision and a
      stale-on-disk one are the same case.
    """
    # Built-ins first, installed plugins after (ticket 05): builders run in
    # order and every write stamps its owner, so the mechanical ladder claims
    # its topics before anything a `pip install` added can, and a plugin that
    # wants one anyway is refused as a collision rather than overwriting.
    from openstategraph.extensions import entry_point_knowledge_builders

    discovered = entry_point_knowledge_builders()
    registered = list(BUILDERS) + list(discovered.values)

    builders = registered
    if source is not None:
        builders = [b for b in registered if b.source_kind == source]
        if not builders:
            known = ", ".join(sorted(b.source_kind for b in registered))
            raise UnknownSourceError(f"Unknown knowledge source '{source}'. Known: {known}")

    written: list[str] = []
    skipped: list[str] = []
    collisions: list[str] = []
    # A plugin that could not load is a source this build silently did not
    # consult; reporting it here is the same "degrade loud" rule as everywhere.
    warnings: list[str] = list(discovered.warnings)
    sources: dict[str, dict[str, list[str]]] = {}
    for builder in builders:
        if isinstance(builder, AgenticKnowledgeBuilder):
            # The escalation ladder's second rung: not enumerable, so no
            # discover/build split — one bounded exploration through the
            # workflow's own read-only tools, writing solely via the store
            # seam. `instruction` is the developer's optional steering text.
            exploration = builder.explore(
                workflow_dir, document, workflows_root, model, instruction=instruction
            )
            if not exploration.touched:
                continue
            entry = sources.setdefault(
                builder.source_kind,
                {"written": [], "skipped": [], "collisions": [], "warnings": []},
            )
            entry["written"].extend(exploration.written)
            entry["skipped"].extend(exploration.skipped)
            entry["collisions"].extend(exploration.collisions)
            entry["warnings"].extend(exploration.warnings)
            entry["uncovered"] = list(exploration.uncovered)
            written.extend(exploration.written)
            skipped.extend(exploration.skipped)
            collisions.extend(exploration.collisions)
            warnings.extend(exploration.warnings)
            continue
        discovery = builder.discover(workflow_dir, document, workflows_root)
        if not discovery.topics and not discovery.warnings:
            continue
        entry = sources.setdefault(
            builder.source_kind,
            {"written": [], "skipped": [], "collisions": [], "warnings": []},
        )
        entry["warnings"].extend(discovery.warnings)
        warnings.extend(discovery.warnings)
        for topic in discovery.topics:
            name = BaseKnowledge.normalize(topic.name)
            other = builder.collides_with(workflow_dir, topic)
            if other is not None:
                message = f"{name}: owned by builder '{other}', refused for '{builder.source_kind}'"
                collisions.append(message)
                entry["collisions"].append(message)
                continue
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
    return {
        "written": written,
        "skipped": skipped,
        "collisions": collisions,
        "warnings": warnings,
        "sources": sources,
    }


# No `__all__` here on purpose. In Python `__all__` reads as "this is the
# public surface", and this module is Tier 3 — internal, no stability
# guarantee (see `openstategraph/api/__init__.py`). The names it exported
# were the ones it hands its own siblings, and a third party would have read
# that as a promise. `openstategraph.__all__` and `openstategraph.abc` are
# the promises.
