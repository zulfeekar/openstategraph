import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  DEFAULT_WORKFLOW_MANAGER_TAB,
  WORKFLOW_MANAGER_TABS,
  type WorkflowManagerTabId,
} from './workflowManagerTabs';

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

describe('the Workflows panel tabs (ticket 41)', () => {
  it('is exactly three tabs: New, Saved, Examples — no fourth word for a settled concept', () => {
    expect(WORKFLOW_MANAGER_TABS.map((t) => t.id)).toEqual(['new', 'saved', 'examples']);
    expect(WORKFLOW_MANAGER_TABS.map((t) => t.label)).toEqual(['New', 'Saved', 'Examples']);
  });

  it('defaults to Saved — a returning reader lands on their own work, not the gallery', () => {
    expect(DEFAULT_WORKFLOW_MANAGER_TAB).toBe<WorkflowManagerTabId>('saved');
  });
});

describe('the second half of ticket 41 — the examples button word', () => {
  const source = read('./WorkflowManager.tsx');

  it('the examples row says Copy, matching copy-on-use — not Open', () => {
    // Established with evidence before this ticket touched anything: the
    // gallery's action button already read "Copy" (`handleCopyExample`),
    // requesting `POST /api/examples/{slug}/copy`, which duplicates the
    // package into `workflows/` and leaves the shipped original untouched.
    // Case 1 of the ticket's three ("it copies -> the label is wrong") does
    // not apply: the label already matched the behaviour. This test pins
    // that so a future edit cannot silently reintroduce "Open" here.
    const examplesSection = source.slice(source.indexOf('heading="Examples"'));
    expect(examplesSection).toContain('handleCopyExample');
    expect(examplesSection).toMatch(/>\s*Copy/);
    expect(examplesSection).not.toContain('>Open<');
  });

  it('the Saved Workflows row still says Open — it edits your own file, not a copy-on-use gallery', () => {
    const savedSection = source.slice(
      source.indexOf('heading="Saved Workflows"'),
      source.indexOf('heading="Examples"'),
    );
    expect(savedSection).toContain('handleLoad');
    expect(savedSection).toMatch(/>\s*Open\s*</);
  });
});
