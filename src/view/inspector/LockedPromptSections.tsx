import { useEffect, useState } from 'react';
import { runtimeBaseUrl } from '@core/runtime/runtimeBaseUrl';

/**
 * The machinery's own prompt sections, shown read-only — tickets 31 and 39.
 *
 * A developer writing rules for an Agent/Router/Grader/Supervisor needs to see
 * what the base already says so they neither duplicate nor contradict it.
 * Served from the Python ladder classes — the single source of truth — and
 * fetched once per app lifetime; a dead backend just means the section stays
 * absent, which is honest (the sections belong to the runtime that isn't
 * there).
 *
 * **Three layers, and only two of them are locked.** The preamble runs first
 * and the output contract always renders last; `default_rules` is what the
 * base already tells the model, and the developer's rules *extend* it unless
 * they switch to replace mode. They are labelled differently for that reason.
 * An Agent has no preamble and no contract by design, so `default_rules` is
 * its only such layer — which is why this panel used to vanish entirely for
 * the most-placed node in the product (ticket 39).
 */
type Sections = { preamble: string; contract: string; default_rules?: string };
type ContractMap = Record<string, Sections>;

let cache: ContractMap | null = null;
let pending: Promise<ContractMap> | null = null;

async function fetchContracts(): Promise<ContractMap> {
  if (cache) return cache;
  pending ??= fetch(`${runtimeBaseUrl()}/api/node-contracts`)
    .then(async (response) => (response.ok ? ((await response.json()) as ContractMap) : {}))
    .catch(() => ({}) as ContractMap)
    .then((map) => (cache = map));
  return pending;
}

export function LockedPromptSections({ nodeType }: { nodeType: string }) {
  const [sections, setSections] = useState<Sections | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchContracts().then((map) => {
      if (!cancelled) setSections(map[nodeType] ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [nodeType]);

  // `default_rules` counts (ticket 39). An agent locks no preamble and no
  // output contract — it answers free-form, deliberately — so the old
  // two-field test hid this panel entirely for the most-placed node in the
  // product, while the base went on prepending its honesty and tool-discipline
  // rules to every prompt. The one family whose machinery is *only*
  // `default_rules` was the one family that could not see its machinery.
  const defaults = sections?.default_rules ?? '';
  if (!sections || (!sections.preamble && !sections.contract && !defaults)) return null;

  return (
    <div className="inspector__locked" aria-label="Prompt sections the machinery supplies">
      {sections.preamble ? (
        <p className="inspector__locked-row">
          <span className="inspector__locked-tag">locked · runs first</span>
          {sections.preamble}
        </p>
      ) : null}
      {sections.contract ? (
        <p className="inspector__locked-row">
          <span className="inspector__locked-tag">locked · always last</span>
          {sections.contract}
        </p>
      ) : null}
      {/* Labelled a default rather than locked, and the distinction is real:
          this text is replaceable from the card's own replace-mode switch, so
          "locked" would be the second untruth in place of the first. */}
      {defaults ? (
        <p className="inspector__locked-row">
          <span className="inspector__locked-tag">default · your rules extend it</span>
          {defaults}
        </p>
      ) : null}
    </div>
  );
}
