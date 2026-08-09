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
from pathlib import Path
from typing import Protocol, runtime_checkable

_TOPIC_RE = re.compile(r"[^a-z0-9]+")


class UnknownTopicError(KeyError):
    """A lookup for a topic the store does not hold.

    Carries the available topics so the caller — above all the lookup tool —
    can answer with the *menu* rather than a bare miss: a model that asked
    for the wrong table name gets the right ones to try next.
    """

    def __init__(self, topic: str, available: list[str]) -> None:
        super().__init__(topic)
        self.topic = topic
        self.available = available


@runtime_checkable
class IKnowledge(Protocol):
    """The contract consumers depend on. Two members, deliberately."""

    def topics(self) -> list[str]: ...

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

    @abstractmethod
    def topics(self) -> list[str]:
        """Every topic this store can answer for, sorted."""

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

    def __init__(self, package_dir: Path) -> None:
        self._directory = Path(package_dir) / "knowledge"

    def topics(self) -> list[str]:
        if not self._directory.is_dir():
            return []
        return sorted(path.stem for path in self._directory.glob("*.md"))

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


__all__ = ["BaseKnowledge", "IKnowledge", "PackageKnowledge", "UnknownTopicError"]
