import { useEffect, useState } from 'react';

/**
 * The machinery's own prompt sections, shown read-only — ticket 31.
 *
 * A developer writing rules for a Router/Grader/Supervisor needs to see what
 * the base already says (the locked preamble and the output contract that
 * always renders last) so they neither duplicate nor contradict it. Served
 * from the Python ladder classes — the single source of truth — and fetched
 * once per app lifetime; a dead backend just means the section stays absent,
 * which is honest (the sections belong to the runtime that isn't there).
 */
type ContractMap = Record<string, { preamble: string; contract: string }>;

let cache: ContractMap | null = null;
let pending: Promise<ContractMap> | null = null;

async function fetchContracts(): Promise<ContractMap> {
  if (cache) return cache;
  pending ??= fetch('http://localhost:8000/api/node-contracts')
    .then(async (response) => (response.ok ? ((await response.json()) as ContractMap) : {}))
    .catch(() => ({} as ContractMap))
    .then((map) => (cache = map));
  return pending;
}

export function LockedPromptSections({ nodeType }: { nodeType: string }) {
  const [sections, setSections] = useState<{ preamble: string; contract: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchContracts().then((map) => {
      if (!cancelled) setSections(map[nodeType] ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [nodeType]);

  if (!sections || (!sections.preamble && !sections.contract)) return null;

  return (
    <div className="inspector__locked" aria-label="Locked prompt sections">
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
    </div>
  );
}
