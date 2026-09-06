import { describe, expect, it } from 'vitest';
import { matchesQuery } from '@core/model/ModelRegistry';
import type { FieldSchema } from '@core/model/contracts/fields';
import type { INodeDefinition } from '@core/model/contracts/node';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { createRouterNode, ROUTER_MATCH_MODE_HINT } from './RouterNode';
import { createOrchestratorNode } from '../orchestrate/OrchestratorNode';

/**
 * `organisms-first-class/39` — *a developer looking for parallel routing will
 * look on the Router.*
 *
 * LangChain's `multi-agent/router.mdx` teaches two shapes under one word:
 * `Command` for single-agent routing, `Send` for parallel fan-out. In this
 * product those are two node families, and **the editor said nothing about the
 * boundary**. Measured in the browser before this was written, against the
 * shipped `dist/` at `5549a1b`:
 *
 * - the palette search `parallel` returned **no rows at all** — neither family;
 * - the Router's description, which is its palette row, its palette hover title
 *   *and* the sentence at the top of its inspector, read *"Classifies the input
 *   and sends it down one branch."*
 *
 * That second line was also **untrue**. The ticket was filed believing the
 * Router is the single-destination family and the Orchestrator the parallel
 * one, and `every-workflow-green` 27 had since superseded that: `matchMode:
 * "all"` makes `BaseRouter.normalise` return a *set* of branches,
 * `_router_for` returns a list, and LangGraph runs every destination in the
 * next superstep. So the honest boundary is **not** one-versus-many. It is
 * whether the destinations are the ones drawn on the node:
 *
 * - **Router** — a fixed, declared set. `compile_path_map()` hands the compiler
 *   every destination up front; "best" takes one of them, "every match" takes
 *   each one that matched. Neither invents a destination.
 * - **Orchestrator** — the *count* is only known during the run.
 *   `_fan_out_router` reads the plan and builds one `Send` per subtask, so one
 *   worker node runs as many times as the input needs.
 *
 * These assertions are against the modules' exports, never against source
 * bytes: `vitest` runs `environment: 'node'` with no jsdom, and `6a8154f` is
 * the commit that paid for testing bytes a formatter can move.
 */
const providers = new ProviderRegistry(new CredentialStore(false));
const router = createRouterNode(providers);
const orchestrator = createOrchestratorNode(providers);

function fieldNamed(definition: INodeDefinition, key: string): FieldSchema {
  const found = definition.fields?.find((field) => field.key === key);
  if (!found) throw new Error(`no field ${key} on ${definition.id}`);
  return found;
}

describe('a developer searching the palette for parallel routing', () => {
  /**
   * The outcome the ticket is about. Not "the Router mentions the
   * Orchestrator" — **both families answer the word**, so the search shows a
   * choice rather than one answer that happens to be reachable.
   */
  it('is shown both families, not one of them', () => {
    expect(matchesQuery(router, 'parallel')).toBe(true);
    expect(matchesQuery(orchestrator, 'parallel')).toBe(true);
  });

  it('finds them by the words that page uses for the shape', () => {
    for (const term of ['fan out', 'fan-out', 'at once']) {
      expect(matchesQuery(orchestrator, term), `orchestrator/${term}`).toBe(true);
    }
    for (const term of ['branch', 'parallel']) {
      expect(matchesQuery(router, term), `router/${term}`).toBe(true);
    }
  });

  /**
   * The guard on the widening. A search box that answers everything is a
   * search box that answers nothing — `paletteSearch` narrows on every term,
   * and these two must not become the reply to an unrelated word.
   */
  it('does not turn either family into a match for an unrelated word', () => {
    for (const term of ['sqlite', 'reddit', 'memory', 'approval', 'email']) {
      expect(matchesQuery(router, term), `router/${term}`).toBe(false);
      expect(matchesQuery(orchestrator, term), `orchestrator/${term}`).toBe(false);
    }
  });
});

describe('the sentence at the top of the Router inspector', () => {
  /**
   * `Inspector.tsx` renders `definition.description` under the node's title,
   * and `Palette.tsx` renders the same string twice — as the row's second line
   * and as its hover title. One string, three surfaces, and it was the one
   * claiming the Router sends the input down exactly one branch.
   */
  it('no longer claims a Router only ever takes one branch', () => {
    // The defect was never the phrase — it was the full stop after it, which
    // made one branch the *whole* behaviour. "one branch" survives as the
    // first half of a sentence that goes on, so the assertion is about where
    // the sentence ends rather than about a substring.
    expect(router.description.toLowerCase()).not.toMatch(/down one branch\.\s*$/);
    expect(router.description.toLowerCase()).toContain('parallel');
  });

  it('still says what the node is before it says what else it can do', () => {
    expect(router.description.toLowerCase()).toContain('classif');
  });
});

describe('the mode that is where the choice is actually made', () => {
  it('carries a hint, which it did not before', () => {
    expect(ROUTER_MATCH_MODE_HINT.length).toBeGreaterThan(0);
    expect(fieldNamed(router, 'matchMode').hint).toBe(ROUTER_MATCH_MODE_HINT);
  });

  /**
   * `2e9c75c`'s precedent — name who owns the thing rather than merely
   * refusing. A hint that said only "this runs several branches" would leave
   * the developer whose count is not known until the run with nowhere to go.
   */
  it('names the Orchestrator as the owner of the other shape', () => {
    expect(ROUTER_MATCH_MODE_HINT).toContain('Orchestrator');
  });

  /**
   * The half that would go green against the ticket's own — superseded —
   * summary. A hint that sent every fan-out to the Orchestrator would name it
   * too, and would be wrong: this Router fans out, and the mode this hint is
   * attached to is how.
   */
  it('says the Router itself runs the matching branches together', () => {
    expect(ROUTER_MATCH_MODE_HINT.toLowerCase()).toContain('parallel');
  });

  /**
   * The distinction that makes the sentence worth reading at all: a Router
   * chooses among destinations that are already drawn, an Orchestrator decides
   * how many there are while the run is happening.
   */
  it('names the property that separates them, not a vaguer difference', () => {
    const hint = ROUTER_MATCH_MODE_HINT.toLowerCase();
    expect(hint).toContain('drawn on this node');
    expect(hint).toMatch(/only known|not known/);
  });
});

describe('the copy teaches no word the lexicon has already spent', () => {
  const strings = [router.description, ROUTER_MATCH_MODE_HINT];

  it('says neither loop, template, nor subgraph', () => {
    for (const text of strings) {
      expect(text.toLowerCase(), text).not.toMatch(/\bloop\b|\btemplate\b|subgraph/);
    }
  });

  it('never calls the step budget a count of laps', () => {
    for (const text of strings) {
      expect(text.toLowerCase(), text).not.toMatch(/iterations?\b|\bturns\b/);
    }
  });

  /**
   * **Scoped to what this platform can publish.** The ticket wanted the
   * developer to learn what choosing a decision tree *cost* them, and the
   * comparison it asks for does not exist: `RunResult.usage` is keyed by
   * **model**, not by node (`4026bb9`), and the HTTP and MCP doors do not
   * carry it at all. So the copy says what each shape *does* and promises no
   * number. CLAUDE.md: do not promise which is not possible.
   */
  it('promises no cost or speed comparison the platform cannot show', () => {
    for (const text of strings) {
      expect(text.toLowerCase(), text).not.toMatch(/faster|cheaper|slower|token|cost/);
    }
  });
});

/**
 * The half the ticket asked for by name — *"on the card"*.
 *
 * The description is on the card, but `NodeCard` truncates a subtitle to one
 * line with an ellipsis, so the clause about parallelism did not survive the
 * trip. The control does: a Router set to broadcast now says so on the canvas,
 * where before the two behaviours drew identically.
 */
describe('what a reader can see without selecting the node', () => {
  it('shows the match mode on the card', () => {
    expect(fieldNamed(router, 'matchMode').onCard).toBe(true);
  });

  /**
   * And the fields that stay off it. A card that showed everything would be
   * the clutter this was weighed against — the fallback branch and the runtime
   * tier change no wiring and are read once, so they remain inspector-only.
   */
  it('does not put the rest of the inspector on it', () => {
    expect(fieldNamed(router, 'fallback').onCard).toBe(false);
    expect(fieldNamed(router, 'tier').onCard).toBe(false);
  });
});
