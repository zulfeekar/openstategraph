import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/**
 * `the-cost-of-one-more/15` — the panel reports "a run is open" upward, and
 * that report must be about a **change of state**, never about a render.
 *
 * The shell passes `onRunningChange` as an inline arrow, so its identity
 * changes on every `AppShell` render. While the reporting effect listed that
 * identity among its dependencies, the effect fired once per render and
 * called `setBackendRunning` from inside the passive-effect commit — a nested
 * update. React's same-value bail-out ends that in one lap on a quiet page;
 * under a burst of `update` frames arriving with no yield between them the
 * fiber always has pending work, the bail-out never applies, and at fifty
 * nested updates React throws #185 and the editor is replaced by its error
 * boundary. Two thousand stubbed frames killed it, reproducibly.
 *
 * **This test is a proxy and is written down as one.** It reads the source
 * rather than the behaviour, because the behaviour is React's reconciler and
 * the unit suite runs in `node` with no DOM (`vite.config.ts`, deliberately).
 * The real reproduction is `e2e/aBurstOfFramesDoesNotKillTheEditor.spec.ts`,
 * which drives two thousand frames at a real browser; this one exists so the
 * seam cannot be re-broken by an edit that never runs the e2e suite.
 *
 * What it does **not** claim: that no other render loop is possible. A
 * dependency array is one route to one, and this pins that route only.
 */
const source = readFileSync(fileURLToPath(new URL('./AskPanel.tsx', import.meta.url)), 'utf8');

describe('the running report', () => {
  it('depends on the state it reports, not on the identity of the reporter', () => {
    expect(source).toContain('runningChangeRef.current?.(running);\n  }, [running]);');
  });

  it('never takes the callback prop as a dependency of an effect that calls it', () => {
    // The one effect allowed to name `onRunningChange` is the mirror that
    // refreshes the ref — it assigns, it does not call.
    const naming = [...source.matchAll(/\}, \[([^\]]*)\]\);/g)]
      .map((match) => match[1] ?? '')
      .filter((deps) => deps.includes('onRunningChange'));
    expect(naming).toEqual(['onRunningChange']);
  });

  it('declares the ref above the effects that read it', () => {
    const declaration = source.indexOf('const runningChangeRef = useRef(onRunningChange);');
    const firstRead = source.indexOf('runningChangeRef.current?.(');
    expect(declaration).toBeGreaterThan(-1);
    expect(firstRead).toBeGreaterThan(declaration);
  });
});
