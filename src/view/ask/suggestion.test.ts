import { describe, expect, it } from 'vitest';
import { applicableSuggestion, type EditorFacts,
  suggestionOutcome,
  unreadyFields,
} from './suggestion';

/**
 * The fence-parsing half of these tests moved to the backend with the
 * boundary — `backend/tests/test_audience_boundary.py` proves over the real
 * `/api/runs/stream` that a suggestion never rides the answer text for any
 * audience. What is left here is the half only the browser can answer: is
 * this suggestion applicable to the canvas that is actually open?
 */

const facts: EditorFacts = {
  nodeTypes: new Set(['tool.web-search', 'tool.web-fetch']),
  nodeIds: new Set(['agent-analyst', 'input-1']),
};

const valid = {
  nodeType: 'tool.web-search',
  attachTo: 'agent-analyst',
  port: 'tools',
  label: 'Web Search',
  reason: 'This workflow has no web access.',
};

describe('applicableSuggestion', () => {
  it('is null when the run carried no developer channel at all', () => {
    // The customer case — and the one this must never mistake for "an empty
    // suggestion", because the run was not entitled to one.
    expect(applicableSuggestion(null, facts)).toBeNull();
    expect(applicableSuggestion(undefined, facts)).toBeNull();
  });

  it('reads a well-formed suggestion', () => {
    expect(applicableSuggestion(valid, facts)).toEqual(valid);
  });

  it('defaults the port to the agent tool bus', () => {
    const suggestion = applicableSuggestion(
      { nodeType: 'tool.web-search', attachTo: 'agent-analyst' },
      facts,
    );
    expect(suggestion?.port).toBe('tools');
  });

  it('rejects a node type this editor does not know', () => {
    const suggestion = applicableSuggestion(
      { nodeType: 'tool.telepathy', attachTo: 'agent-analyst' },
      facts,
    );
    expect(suggestion).toBeNull();
  });

  it('rejects an attachTo that is not in the document', () => {
    const suggestion = applicableSuggestion(
      { nodeType: 'tool.web-search', attachTo: 'agent-ghost' },
      facts,
    );
    expect(suggestion).toBeNull();
  });

  it('rejects non-string fields rather than coercing them', () => {
    // A model that answers with a number where a node type belongs has not
    // named a node type, and pretending otherwise offers a button that fails.
    expect(applicableSuggestion({ nodeType: 42, attachTo: 'agent-analyst' }, facts)).toBeNull();
  });

  it('rejects an array — a suggestion is one object', () => {
    expect(applicableSuggestion([] as unknown as Record<string, unknown>, facts)).toBeNull();
  });
});

/**
 * `the-agent-asks-for-what-it-cannot-get` 01 — the owner's transcript.
 *
 * Three accepts of one suggestion produced three `Email Send` nodes on one bus,
 * three identical "No recipient configured" failures, and no progress. Every
 * mechanism worked as designed; nothing asked the two questions below.
 */
describe('a suggestion for a tool that is already there', () => {
  const facts = (wired: Record<string, string[]> = {}) => ({
    nodeTypes: new Set(['tool.email-send', 'tool.web-search']),
    nodeIds: new Set(['a-account']),
    wired: new Map(Object.entries(wired).map(([k, v]) => [k, new Set(v)])),
  });
  const raw = {
    nodeType: 'tool.email-send',
    attachTo: 'a-account',
    port: 'tools',
    label: 'Email Send',
    reason: 'no way to send the ticket',
  };

  it('is refused before the card is offered, not after it is pressed', () => {
    const outcome = suggestionOutcome(raw, facts({ 'a-account:tools': ['tool.email-send'] }));
    expect(outcome.kind).toBe('duplicate');
  });

  it('says where it already is, and that a second one would not help', () => {
    const outcome = suggestionOutcome(raw, facts({ 'a-account:tools': ['tool.email-send'] }));
    if (outcome.kind !== 'duplicate') throw new Error('expected duplicate');
    // "Already added" leaves a reader hunting a canvas for which one, and says
    // nothing about what to do instead.
    expect(outcome.message).toContain('Email Send');
    expect(outcome.message).toContain('already wired');
    expect(outcome.message).toMatch(/check its settings/);
  });

  it('still applies when a different tool is on the same bus', () => {
    // Two different tools on one bus is legitimate, and is what the offsetting
    // in `applySuggestion` was written for. Only the same type is refused.
    const outcome = suggestionOutcome(raw, facts({ 'a-account:tools': ['tool.web-search'] }));
    expect(outcome.kind).toBe('apply');
  });

  it('still applies when the same tool is on a different agent', () => {
    const outcome = suggestionOutcome(raw, facts({ 'other:tools': ['tool.email-send'] }));
    expect(outcome.kind).toBe('apply');
  });

  it('keeps refusing a malformed suggestion the way it always did', () => {
    expect(suggestionOutcome({ ...raw, nodeType: 'tool.nope' }, facts()).kind).toBe('none');
    expect(suggestionOutcome({ ...raw, attachTo: 'ghost' }, facts()).kind).toBe('none');
    expect(suggestionOutcome(null, facts()).kind).toBe('none');
  });
});

describe('a node that cannot run yet', () => {
  const EMAIL = [
    { key: 'to', label: 'Recipient', required: true },
    { key: 'subject', label: 'Subject' },
  ];

  it('names the required field that has no value', () => {
    // The failure the transcript spent a model call discovering: added with an
    // empty `to`, wired, re-run, "No recipient configured".
    expect(unreadyFields(EMAIL, {})).toEqual(['Recipient']);
    expect(unreadyFields(EMAIL, { to: '   ' })).toEqual(['Recipient']);
  });

  it('is ready once the value is there', () => {
    expect(unreadyFields(EMAIL, { to: 'zee@example.com' })).toEqual([]);
  });

  it('ignores fields nobody said were required', () => {
    // `required` is not `validate`: this is about absence, and only a field
    // that declared itself required gets to block a run.
    expect(unreadyFields([{ key: 'subject', label: 'Subject' }], {})).toEqual([]);
  });

  it('falls back to the key when a field has no label', () => {
    expect(unreadyFields([{ key: 'to', required: true }], {})).toEqual(['to']);
  });
});
