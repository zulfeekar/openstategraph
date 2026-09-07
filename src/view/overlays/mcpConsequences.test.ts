import { describe, expect, it } from 'vitest';
import {
  mcpDeleteConfirmation,
  mcpDeletedMessage,
  mcpRestoredMessage,
  restoreDefaultsLabel,
} from './mcpConsequences';

/**
 * mcp-connect ticket 06 — *"deleting asks first, and says which it is
 * deleting"*, and a `default` says what deletion actually does.
 *
 * The copy is the feature. A confirm that says "are you sure?" has told
 * nobody that the row they are about to remove is recoverable, and that was
 * the whole complaint: the tombstone mechanism is good and undiscoverable.
 */

describe('mcpDeleteConfirmation', () => {
  it('names the server it is about to delete', () => {
    expect(mcpDeleteConfirmation('LangChain docs', 'built-in')).toContain('LangChain docs');
  });

  it('tells a default it is hidden rather than destroyed, and points at the way back', () => {
    const text = mcpDeleteConfirmation('LangChain docs', 'built-in');

    expect(text).toContain('hidden for this project');
    expect(text).toContain('Restore defaults');
    expect(text).not.toContain('config file');
  });

  it('is plain text, because window.confirm renders no markdown', () => {
    // Shipped once: the dialog read "**Restore defaults**", asterisks and all.
    expect(mcpDeleteConfirmation('LangChain docs', 'built-in')).not.toContain('*');
    expect(mcpDeleteConfirmation('Internal docs', 'project', ['a'])).not.toContain('*');
  });

  it('tells a project entry the truth about itself instead', () => {
    const text = mcpDeleteConfirmation('Internal docs', 'project');

    expect(text).toContain('config file');
    expect(text).not.toContain('hidden for this project');
    // No promise it cannot keep: a deleted project entry has no URL to come
    // back from, so nothing offers to restore it.
    expect(text).not.toContain('Restore defaults');
  });

  it('names the saved workflows a delete would break', () => {
    const text = mcpDeleteConfirmation('LangChain docs', 'built-in', ['docs-bot', 'support']);

    expect(text).toContain('2 saved workflows name it');
    expect(text).toContain('docs-bot, support');
  });

  it('agrees with itself about one workflow', () => {
    const text = mcpDeleteConfirmation('LangChain docs', 'built-in', ['docs-bot']);

    expect(text).toContain('One saved workflow names it — docs-bot');
    expect(text).toContain('Its MCP card will stop resolving');
  });

  it('says nothing about breakage when nothing names it', () => {
    expect(mcpDeleteConfirmation('LangChain docs', 'built-in')).not.toContain('name it');
  });
});

describe('mcpDeletedMessage', () => {
  it('keeps the confirm’s promise in the toast', () => {
    expect(mcpDeletedMessage('LangChain docs', 'built-in')).toContain('hidden');
    expect(mcpDeletedMessage('Internal docs', 'project')).toContain('Deleted');
  });
});

describe('mcpRestoredMessage', () => {
  it('says what came back', () => {
    expect(mcpRestoredMessage('LangChain docs')).toContain('LangChain docs');
  });
});

describe('restoreDefaultsLabel', () => {
  it('is nothing at all when nothing is hidden', () => {
    expect(restoreDefaultsLabel([])).toBeNull();
  });

  it('names the one, because the point is that it is findable', () => {
    expect(restoreDefaultsLabel(['LangChain docs'])).toBe('Restore “LangChain docs”');
  });

  it('counts them when there is more than one', () => {
    expect(restoreDefaultsLabel(['a', 'b'])).toBe('Restore 2 hidden defaults');
  });
});
