/**
 * What kind of knowledge doc a topic is — ticket 13.
 *
 * The card listed every topic in one undifferentiated list, badged with the
 * marker's own source word (`root`, `explorer`, `sql`, or `claimed`). All the
 * information was there and none of the *meaning* was: telling `root` from
 * `explorer` requires knowing the builder registry, which nobody reading a
 * card does.
 *
 * Two questions a doc can answer, and they are not the same question:
 *
 * - **routes** — *where does this kind of question go?* The gateway's store is
 *   mostly these, written by the builders that enumerate workflows.
 * - **explains** — *what does this mean?* One per table, per subject, per file.
 *
 * That is why a fabricated doc about a search-tool vendor was out of place in
 * `concierge` — it was the only *explains* in a store full of *routes*, and the
 * card gave a reader no way to see it. It surfaced days later through a failing
 * test instead.
 *
 * And the third, which the ticket is right to call the important one: a doc
 * with **no marker** is one a human owns and no builder will ever overwrite.
 * That is a promise, and it is what someone most wants to be sure of before
 * they start editing.
 *
 * **The source vocabulary is not invented here.** The marker's words are the
 * ones that exist; this maps them to the question they answer and keeps the
 * word itself in the tooltip. A source this does not know about falls through
 * as itself rather than being guessed at — a new builder shows up honestly as
 * its own name instead of being mislabelled by a stale list.
 */

/** Builders whose topics are pointers at workflows. `knowledge_builders.py`. */
const ROUTING_SOURCES = new Set(['root', 'project']);

/** Builders whose topics are subjects: one per table, per topic, per file. */
const CONCEPT_SOURCES = new Set(['sql', 'explorer', 'codebase']);

export interface TopicKind {
  /** The badge. Three words, and each answers a different question. */
  readonly label: string;
  /** The hover, which carries the marker's own vocabulary. */
  readonly title: string;
}

export function topicKind(topic: { generated: boolean; source: string }): TopicKind {
  if (!topic.generated) {
    return {
      label: 'yours',
      title: 'Hand-authored. No builder will overwrite it — that is what claiming a doc means.',
    };
  }
  if (ROUTING_SOURCES.has(topic.source)) {
    return {
      label: 'routes',
      title: `Where this kind of question goes. Written by the "${topic.source}" builder.`,
    };
  }
  if (CONCEPT_SOURCES.has(topic.source)) {
    return {
      label: 'explains',
      title: `What this means, rather than where it goes. Written by the "${topic.source}" builder.`,
    };
  }
  return {
    label: topic.source || 'generated',
    title: topic.source
      ? `Written by the "${topic.source}" builder.`
      : 'Generated, by a builder that did not record which.',
  };
}
