import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ambientTools, onAmbientToolsChange, setAmbientTools } from './ambientTools';

/**
 * What every agent gets without being wired to it (`every-workflow-green` 05a).
 *
 * An agent on a canvas with two tools drawn actually had five: the prebuilt
 * memory tools bind to *every* agent when the server has a store configured.
 * The truth surfaced only because a model hallucinated a tool name and the
 * runtime listed the real ones — nothing reported it.
 *
 * The backend now publishes it on the capabilities response
 * (`ambient_tools`, commit aaca223). This is where the editor keeps it: a
 * store rather than a prop, for the reason `capabilityWarnings` records —
 * it arrives asynchronously, after a load or a Refresh, and it is a
 * **standing** condition rather than an event.
 *
 * **Conditional on the environment, never on the document.** A server with no
 * store binds none, so an empty list is a real answer and must render as
 * nothing at all — not as "none configured", which would be a claim about a
 * workflow rather than about a server.
 */
describe('the ambient tool store', () => {
  beforeEach(() => setAmbientTools([]));

  it('starts empty, because a server may bind none', () => {
    expect(ambientTools()).toEqual([]);
  });

  it('holds what the last capabilities fetch reported', () => {
    setAmbientTools(['forget_memory', 'save_memory', 'search_memory']);
    expect(ambientTools()).toEqual(['forget_memory', 'save_memory', 'search_memory']);
  });

  it('replaces rather than appends', () => {
    // A workflow opened after another must not inherit its predecessor's
    // answer — and a store that binds none must be able to say so.
    setAmbientTools(['save_memory']);
    setAmbientTools([]);
    expect(ambientTools()).toEqual([]);
  });

  it('notifies subscribers so a card can redraw when the answer arrives', () => {
    const handler = vi.fn();
    const off = onAmbientToolsChange(handler);
    setAmbientTools(['save_memory']);
    expect(handler).toHaveBeenCalledOnce();
    off();
    setAmbientTools(['search_memory']);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('returns a stable reference between changes, so useSyncExternalStore cannot loop', () => {
    setAmbientTools(['save_memory']);
    expect(ambientTools()).toBe(ambientTools());
  });
});
