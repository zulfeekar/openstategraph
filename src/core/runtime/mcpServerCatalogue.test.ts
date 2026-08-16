import { describe, expect, it, vi } from 'vitest';
import type { McpServer } from './McpRegistryClient';
import { McpServerCatalogue } from './mcpServerCatalogue';

const server = (name: string, origin = 'project'): McpServer => ({
  name,
  url: `https://${name}.test/mcp`,
  transport: 'streamable_http',
  auth: { kind: 'none', headerName: '', tokenEnv: '' },
  origin,
  credentialConfigured: false,
});

describe('the registry, answerable during a render', () => {
  it('says it has not been told, which is not the same as an empty registry', () => {
    // The whole bug in one distinction. A picker that cannot tell "nobody has
    // asked yet" from "there are none" has to guess, and guessing wrong in
    // either direction is a ghost entry or a blank dropdown.
    expect(new McpServerCatalogue().list()).toBeNull();
  });

  it('holds the names the registry answered with', () => {
    const catalogue = new McpServerCatalogue();
    catalogue.set([server('Needs auth'), server('LangChain docs', 'built-in')]);
    expect(catalogue.list()).toEqual(['Needs auth', 'LangChain docs']);
  });

  it('an empty answer is an answer, and stays empty', () => {
    const catalogue = new McpServerCatalogue();
    catalogue.set([]);
    expect(catalogue.list()).toEqual([]);
  });

  it('notifies when the list moves and stays quiet when it does not', () => {
    const catalogue = new McpServerCatalogue();
    const listener = vi.fn();
    catalogue.onChange(listener);

    catalogue.set([server('Needs auth')]);
    expect(listener).toHaveBeenCalledTimes(1);

    // The panel re-lists after every validate press.
    catalogue.set([server('Needs auth')]);
    expect(listener).toHaveBeenCalledTimes(1);

    catalogue.set([server('Needs auth'), server('Bogus host')]);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it('lets a listener go', () => {
    const catalogue = new McpServerCatalogue();
    const listener = vi.fn();
    catalogue.onChange(listener)();
    catalogue.set([server('Needs auth')]);
    expect(listener).not.toHaveBeenCalled();
  });
});
