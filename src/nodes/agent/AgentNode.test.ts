import { describe, expect, it } from 'vitest';

import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { MockProvider } from '@core/providers/MockProvider';
import { defaultsFrom } from '@core/model/contracts/fields';

import { createAgentNode } from './AgentNode';

function agentFields() {
  const providers = new ProviderRegistry(new CredentialStore(false));
  providers.register(new MockProvider(0));
  return createAgentNode(providers).fields;
}

describe('the summarize toggle', () => {
  it('is on by default', () => {
    // The owner's decision, 2026-08-15. It was off, unset on all three
    // shipped agents, and — until this wave — wired to a middleware built
    // with no trigger, so the whole feature was a control that reached
    // nothing. Both halves are fixed together: turning it on would be
    // pointless while the middleware could not fire, and making it fire
    // would reach nobody while the toggle stayed off.
    expect(defaultsFrom(agentFields()).summarize).toBe(true);
  });

  it('is still a toggle, so it can be turned off', () => {
    const field = agentFields().find((schema) => schema.key === 'summarize');
    expect(field?.kind).toBe('toggle');
  });

  it('materialises the default into a new node, which is what makes a saved false meaningful', () => {
    // `defaultsFrom` writes every default into `data`, so an agent created
    // before this flip carries a literal `summarize: false` — not an absent
    // key. The backend reads absent as ON and an explicit false as OFF, and
    // that asymmetry is deliberate: it is what keeps opening an old document
    // from silently changing what it does.
    expect('summarize' in defaultsFrom(agentFields())).toBe(true);
  });
});
