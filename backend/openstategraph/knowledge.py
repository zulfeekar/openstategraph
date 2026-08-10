"""The Knowledge atom: ``IKnowledge`` → ``BaseKnowledge`` → ``PackageKnowledge``.

A workflow's *second brain* — procedural knowledge about its domain (what a
table is, what its columns mean, which JOINs are legal, the business logic a
schema alone cannot say), one Markdown file per **topic** under the workflow
package's ``knowledge/`` directory.

**Knowledge is fetched on demand, never concatenated into a system prompt.**
That is the whole reason this module exists. The workflow-level ``skills/``
mechanism loads *everything* into *every* agent's context, which is context
bloat the moment a database has more than a handful of tables. A knowledge
store instead sits behind a tool (``tool.knowledge-lookup``): the model asks
for exactly the topic it is about to use, when it is about to use it, and
pays for nothing else.

The files are plain Markdown in git. Two kinds of consumer read them, and
both matter: workflow agents at runtime (through the lookup tool), and any
coding agent opening ``workflows/<slug>/knowledge/*.md`` directly — the same
docs orient a human or an agent editing the package.

Ladder shape mirrors ``abc/tool.py``: the ``I*`` protocol is the contract
consumers depend on (a shape, not a base class — anything with ``topics()``
and ``lookup()`` participates), the abstract base owns everything shared
(topic normalization, the unknown-topic error carrying the available topics),
and the concrete binds one storage. ``PackageKnowledge`` is file-backed; a
future store (a vector index, a wiki) is a new concrete, never an edit here.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

_TOPIC_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class TopicIndexEntry:
    """One line of the free index tier: a topic name and its one-sentence hint.

    The hint IS the doc's first meaningful line (see ``extract_hint``), so
    the index is self-assembling — authoring the doc authors the index.
    """

    name: str
    hint: str


class UnknownTopicError(KeyError):
    """A lookup for a topic the store does not hold.

    Carries the available topic index entries so the caller — above all the
    lookup tool — can answer with the *menu* rather than a bare miss: a model
    that asked for the wrong table name gets the right ones to try next, each
    with its index hint.
    """

    def __init__(self, topic: str, available: list[TopicIndexEntry]) -> None:
        super().__init__(topic)
        self.topic = topic
        self.available = available


@runtime_checkable
class IKnowledge(Protocol):
    """The contract consumers depend on. Two members, deliberately."""

    def topics(self) -> list[TopicIndexEntry]: ...

    def lookup(self, topic: str) -> str: ...


class BaseKnowledge(ABC):
    """Shared behaviour: normalization and the unknown-topic protocol.

    A subclass supplies ``topics()`` and ``_fetch(normalized_topic)``; the
    base owns the lookup flow so every store misses the same way.
    """

    @staticmethod
    def normalize(topic: str) -> str:
        """One canonical spelling per topic — lowercase, hyphen-separated.

        The same rule ``slugify`` applies to workflow names, and it doubles
        as the traversal guard for file-backed stores: a normalized topic
        cannot contain a path separator or a dot-dot, so it can never name a
        file outside the knowledge directory.
        """
        return _TOPIC_RE.sub("-", topic.strip().lower()).strip("-")

    @staticmethod
    def extract_hint(text: str) -> str:
        """The doc's index line: its first meaningful line, noise stripped.

        Skips blank lines and HTML-comment lines (the generated marker),
        strips a leading Markdown heading prefix. A doc with no meaningful
        first line (empty file, marker-only file) yields an empty hint —
        the topic still appears in the index, just without a sentence.
        """
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("<!--"):
                continue
            return stripped.lstrip("#").strip()
        return ""

    @abstractmethod
    def topics(self) -> list[TopicIndexEntry]:
        """The index tier: every topic with its hint, sorted by name."""

    @abstractmethod
    def _fetch(self, topic: str) -> str | None:
        """The document for one *normalized* topic, or None if absent."""

    def lookup(self, topic: str) -> str:
        text = self._fetch(self.normalize(topic))
        if text is None:
            raise UnknownTopicError(topic, self.topics())
        return text


class PackageKnowledge(BaseKnowledge):
    """A knowledge store backed by ``<package>/knowledge/<topic>.md`` files.

    Read fresh per call, never cached: the files are edited by hand, written
    by the builder, and watched by nothing — a cache here would serve stale
    knowledge for the lifetime of the process.
    """

    def __init__(
        self,
        package_dir: Path | str | None = None,
        *,
        knowledge_dir: Path | str | None = None,
    ) -> None:
        """`knowledge_dir` names the directory of `<topic>.md` files itself.

        The convention — `<package>/knowledge` — stays the default and is what
        every canvas-authored workflow uses. The explicit form exists for the
        cases convention cannot express (knowledge shared between packages, or
        outside the repository); it is what `load_workflow(knowledge_dir=...)`
        threads down to.
        """
        if knowledge_dir is not None:
            self._directory = Path(knowledge_dir)
        elif package_dir is not None:
            self._directory = Path(package_dir) / "knowledge"
        else:
            raise ValueError("PackageKnowledge needs a package_dir or a knowledge_dir")

    def topics(self) -> list[TopicIndexEntry]:
        if not self._directory.is_dir():
            return []
        entries: list[TopicIndexEntry] = []
        for path in sorted(self._directory.glob("*.md"), key=lambda p: p.stem):
            try:
                text = path.read_text()
            except OSError:
                text = ""
            entries.append(TopicIndexEntry(name=path.stem, hint=self.extract_hint(text)))
        return entries

    def _fetch(self, topic: str) -> str | None:
        if not topic:
            return None
        path = self._directory / f"{topic}.md"
        if not path.is_file():
            return None
        try:
            return path.read_text()
        except OSError:
            return None


__all__ = [
    "BaseKnowledge",
    "IKnowledge",
    "PackageKnowledge",
    "TopicIndexEntry",
    "UnknownTopicError",
]
