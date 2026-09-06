import { describe, expect, it } from 'vitest';
import { makeWorkbench } from '@core/testing/fixtures';
import conciergeEnvelope from '../../../workflows/concierge/workflow.json';
import { PLATFORM_TOOL_NODES } from './PlatformToolsNode';
import { EXECUTION_OVERRIDE_KEYS } from '../../core/model/ModelRegistry';

describe('platform tool nodes', () => {
  it('the concierge document survives an editor round-trip intact', () => {
    // The serializer silently drops unregistered node types — this pins that
    // every type the hidden gateway binds exists in the catalogue, so opening
    // it in the editor can never destroy its tools (ticket 67).
    const workbench = makeWorkbench();
    const document = (
      conciergeEnvelope as unknown as { document: { nodes: unknown[]; edges: unknown[] } }
    ).document;
    const outcome = workbench.serializer.loadFromText(workbench.model, JSON.stringify(document));
    expect(outcome.ok).toBe(true);
    if (outcome.ok) expect(outcome.value.warnings).toEqual([]);
    expect(workbench.model.nodes()).toHaveLength(document.nodes.length);
    expect(workbench.model.edges()).toHaveLength(document.edges.length);
  });

  it('ships the Knowledge atom, findable by its second-brain vocabulary', () => {
    // The knowledge layer's canvas face (its Python half is
    // `prebuilt_knowledge.py`): a lookup tool any agent's tools port can
    // bind, fetched on demand rather than concatenated into prompts.
    const knowledge = PLATFORM_TOOL_NODES.find(
      (entry) => entry.definition.id === 'tool.knowledge-lookup',
    );
    expect(knowledge).toBeDefined();
    for (const keyword of ['knowledge', 'brain', 'wiki', 'procedural']) {
      expect(knowledge?.definition.keywords).toContain(keyword);
    }
  });

  it('allows exactly one Knowledge atom per workflow', () => {
    // Ticket 16. One document is one package is one `knowledge/` directory,
    // so a second atom would be a second card claiming the same single store
    // — and two build buttons racing over the same files. `maxInstances`
    // already counts per open document, which is exactly the right scope: a
    // mounted child is a different document, so a root and a team may each
    // hold one. That is the designed shape, not a collision.
    const knowledge = PLATFORM_TOOL_NODES.find(
      (entry) => entry.definition.id === 'tool.knowledge-lookup',
    );
    expect(knowledge?.definition.maxInstances).toBe(1);

    const workbench = makeWorkbench();
    const first = workbench.controller.nodes.add('tool.knowledge-lookup', { x: 0, y: 0 });
    expect(first.ok).toBe(true);
    const second = workbench.controller.nodes.add('tool.knowledge-lookup', { x: 200, y: 0 });
    expect(second.ok).toBe(false);
    expect(workbench.model.countOfType('tool.knowledge-lookup')).toBe(1);
  });

  describe('the YouTube transcript atom', () => {
    const youtube = PLATFORM_TOOL_NODES.find(
      (entry) => entry.definition.id === 'tool.youtube-transcript',
    );

    it('declares the same node type id the Python tool answers to', () => {
      // The seam, tested. If this drifts, the card looks wired and answers
      // nothing — `prebuilt_youtube.YouTubeTranscriptTool.node_type` is the
      // other half, pinned by `backend/tests/test_prebuilt_youtube.py`.
      expect(youtube).toBeDefined();
      expect(youtube?.definition.id).toBe('tool.youtube-transcript');
    });

    it('exposes exactly one out port: the tool bus connector', () => {
      const outs = (youtube?.definition.ports({}) ?? []).filter((port) => port.direction === 'out');
      expect(outs).toHaveLength(1);
      expect(outs[0]?.id).toBe('tool');
    });

    it('declares the three keys `configure` reads, with the Python defaults', () => {
      // A key the Python half reads that no field declares is a control
      // reaching nothing — the defect `test_data_key_contract.py` exists for.
      const fields = new Map(youtube?.definition.fields?.map((f) => [f.key, f]) ?? []);
      // The execution-override keys are injected onto every node type by
      // `ModelRegistry` and read by graph assembly, not by the tool.
      expect([...fields.keys()]).toEqual([
        'language',
        'allowAutoCaptions',
        'maxChars',
        ...EXECUTION_OVERRIDE_KEYS,
      ]);
      expect(fields.get('language')?.defaultValue).toBe('en');
      expect(fields.get('allowAutoCaptions')?.defaultValue).toBe(true);
      expect(fields.get('maxChars')?.defaultValue).toBe(8000);
    });

    it('keeps the truncation budget inside the range the tool clamps to', () => {
      const budget = youtube?.definition.fields?.find((f) => f.key === 'maxChars');
      expect(budget?.kind).toBe('slider');
      if (budget?.kind === 'slider') {
        expect([budget.min, budget.max]).toEqual([1000, 20000]);
      }
    });
  });

  it('states the build-time rule on the atom every developer reads', () => {
    // Invariant 3 of the knowledge architecture, stated where the affordance
    // lives rather than only in a decision record: the button is build-time,
    // and nothing in a compiled graph can reach it.
    const knowledge = PLATFORM_TOOL_NODES.find(
      (entry) => entry.definition.id === 'tool.knowledge-lookup',
    );
    expect(knowledge?.definition.description).toContain('build time');
    expect(knowledge?.definition.description).toContain('a run only ever reads them');
  });
});
