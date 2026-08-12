import { describe, expect, it } from 'vitest';
import { continuingThread, rememberThread, type ThreadBinding } from './thread';

const bound = (slug: string | undefined, id: string): ThreadBinding => ({ slug, id });

describe('continuingThread', () => {
  it('sends nothing when no conversation has started', () => {
    // The defect this file exists for, in its benign form: the first question
    // of a conversation genuinely has no thread, and the server mints one.
    expect(continuingThread(null, 'chinook-assistant')).toBeUndefined();
  });

  it('continues the conversation when the same workflow is still open', () => {
    // The defect in its live form: without this, every send is turn one and
    // "how did you get that?" arrives with no antecedent.
    expect(continuingThread(bound('chinook-assistant', 'run-1'), 'chinook-assistant')).toBe(
      'run-1',
    );
  });

  it('starts a new conversation when a different workflow is opened', () => {
    // The checkpointer is keyed by thread id alone, so reusing this one would
    // replay chinook-assistant's messages into the concierge graph.
    expect(continuingThread(bound('chinook-assistant', 'run-1'), 'concierge')).toBeUndefined();
  });

  it('treats an unsaved canvas as its own conversation, both ways', () => {
    expect(continuingThread(bound(undefined, 'run-1'), 'chinook-assistant')).toBeUndefined();
    expect(continuingThread(bound('chinook-assistant', 'run-1'), undefined)).toBeUndefined();
    expect(continuingThread(bound(undefined, 'run-1'), undefined)).toBe('run-1');
  });
});

describe('rememberThread', () => {
  it('takes the thread a terminal frame named', () => {
    expect(rememberThread(null, 'chinook-assistant', 'run-1')).toEqual({
      slug: 'chinook-assistant',
      id: 'run-1',
    });
  });

  it('keeps what it holds when a frame names no thread', () => {
    // Empty means "this frame told me nothing", never "there was no thread" —
    // clearing here would silently start a second conversation on the next
    // send, which is the original defect wearing a different hat.
    const held = bound('chinook-assistant', 'run-1');
    expect(rememberThread(held, 'chinook-assistant', '')).toBe(held);
  });

  it('returns the identical binding when nothing changed', () => {
    // Referential stability, so a stream of frames naming the same thread does
    // not re-render the panel once per frame.
    const held = bound('chinook-assistant', 'run-1');
    expect(rememberThread(held, 'chinook-assistant', 'run-1')).toBe(held);
  });

  it('rebinds when the server names a different thread', () => {
    // How a new conversation is adopted: the panel forgot its thread, the next
    // run was minted a fresh one, and this is where it lands.
    expect(
      rememberThread(bound('chinook-assistant', 'run-1'), 'chinook-assistant', 'run-2'),
    ).toEqual({ slug: 'chinook-assistant', id: 'run-2' });
  });

  it('rebinds when the same thread id arrives against a different workflow', () => {
    expect(rememberThread(bound('chinook-assistant', 'run-1'), 'concierge', 'run-1')).toEqual({
      slug: 'concierge',
      id: 'run-1',
    });
  });
});
