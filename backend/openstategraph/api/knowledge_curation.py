"""Curation of the second brain — list, read, save (the UI half's backend).

The contract (knowledge-architecture.md, "Curation contract"):

- **Builder generates → developer owns every word.** Saving a doc through
  the PUT endpoint strips the generated marker: human touch = human
  ownership, recorded with no extra ceremony (the auto-claim). A claimed doc
  is never regenerated (`owns()` refuses files without a marker).
- **Stale badges apply to claimed docs too.** Every generated marker stamps
  `hash=<12-hex>` of the topic's introspection brief; claiming records the
  same hash in a trailing HTML comment (`CLAIMED_HASH_COMMENT` — the
  least-invasive spelling: one self-contained file, hidden by renderers).
  The list endpoint recomputes the briefs through the mechanical builders'
  own adapters and badges any doc whose recorded hash no longer matches.
  Agentic topics (explorer/codebase) have no recomputable brief, so they are
  never badged stale — unknown is not stale.
- **Jail**: a topic name is normalized by the same rule as every store path
  (`BaseKnowledge.normalize`); a name that normalizes away, or does not
  round-trip, cannot address a file at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openstategraph.knowledge import BaseKnowledge, PackageKnowledge
from openstategraph.knowledge_builders import (
    CLAIMED_HASH_COMMENT,
    RootKnowledgeBuilder,
    SqlKnowledgeBuilder,
    claimed_hash,
    marker_hash,
    marker_source,
    source_hash,
)


class UnknownTopicPathError(ValueError):
    """A topic name that is not a valid, jailed knowledge slug."""


@dataclass(frozen=True)
class TopicStatus:
    name: str
    hint: str
    generated: bool
    source: str  # owning builder kind; "" for claimed/hand-authored docs
    stale: bool


def _topic_path(workflow_dir: Path, topic: str) -> Path:
    """The one place a topic name becomes a path. Normalize-and-round-trip
    is the jail: 'a/../b' normalizes to 'a-b', never a traversal."""
    name = BaseKnowledge.normalize(topic)
    if not name or name != topic.strip():
        raise UnknownTopicPathError(
            f"'{topic}' is not a topic name — use the normalized slug from the topic list."
        )
    return workflow_dir / "knowledge" / f"{name}.md"


def current_source_hashes(
    workflow_dir: Path, document: dict[str, Any], workflows_root: Path
) -> dict[str, str]:
    """topic → hash of its *current* brief, recomputed through the mechanical
    builders' adapters. Failures yield an empty map (no badge) — a staleness
    hint must never break the listing."""
    hashes: dict[str, str] = {}
    for builder in (SqlKnowledgeBuilder(), RootKnowledgeBuilder()):
        try:
            discovery = builder.discover(workflow_dir, document, workflows_root)
        except Exception:
            continue
        for topic in discovery.topics:
            hashes.setdefault(BaseKnowledge.normalize(topic.name), source_hash(topic.brief))
    return hashes


def list_topics(
    workflow_dir: Path, document: dict[str, Any], workflows_root: Path
) -> list[TopicStatus]:
    current = current_source_hashes(workflow_dir, document, workflows_root)
    statuses: list[TopicStatus] = []
    for entry in PackageKnowledge(workflow_dir).topics():
        text = read_topic(workflow_dir, entry.name)
        owner = marker_source(text)
        generated = owner is not None
        recorded = marker_hash(text) if generated else claimed_hash(text)
        now = current.get(entry.name)
        stale = recorded is not None and now is not None and recorded != now
        statuses.append(
            TopicStatus(
                name=entry.name,
                hint=entry.hint,
                generated=generated,
                source=owner or "",
                stale=stale,
            )
        )
    return statuses


def read_topic(workflow_dir: Path, topic: str) -> str:
    """The raw doc body, marker and all — curation edits the real file."""
    path = _topic_path(workflow_dir, topic)
    if not path.is_file():
        raise FileNotFoundError(topic)
    return path.read_text()


def save_topic(
    workflow_dir: Path,
    topic: str,
    body: str,
    document: dict[str, Any],
    workflows_root: Path,
) -> TopicStatus:
    """Explicit save, with the auto-claim: any generated marker line in the
    saved body is stripped (human touch = human ownership), and the source
    hash the doc was last true to is recorded in the trailing claim comment
    so the stale badge keeps working after the claim."""
    path = _topic_path(workflow_dir, topic)
    name = path.stem
    previous = path.read_text() if path.is_file() else ""

    # Strip only marker LINES (a line starting with the generated marker);
    # everything else the developer wrote is kept verbatim.
    from openstategraph.knowledge_builders import GENERATED_MARKER

    lines = [line for line in body.splitlines() if not line.startswith(GENERATED_MARKER)]
    cleaned = "\n".join(lines).strip()

    # The hash this doc is true to at claim time: the current source hash
    # when the source is still introspectable, else whatever was stamped.
    now = current_source_hashes(workflow_dir, document, workflows_root).get(name)
    recorded = now or marker_hash(previous) or claimed_hash(previous) or claimed_hash(body)
    # One claim comment, always trailing: drop any prior spelling first.
    cleaned = "\n".join(
        line for line in cleaned.splitlines() if not line.strip().startswith(CLAIMED_HASH_COMMENT)
    ).strip()
    trailer = f"\n\n{CLAIMED_HASH_COMMENT}{recorded} -->" if recorded else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{cleaned}{trailer}\n")

    text = path.read_text()
    stale = False  # just claimed against the current source (or unknowable)
    return TopicStatus(
        name=name,
        hint=BaseKnowledge.extract_hint(text),
        generated=False,
        source="",
        stale=stale,
    )


__all__ = [
    "TopicStatus",
    "UnknownTopicPathError",
    "current_source_hashes",
    "list_topics",
    "read_topic",
    "save_topic",
]
