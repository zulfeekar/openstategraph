import { describe, expect, it } from 'vitest';
import { doorHeadline } from './doorHeadline';

describe('doorHeadline', () => {
  it('says what the model said, when the model said something', () => {
    const line = doorHeadline('Need a tool that can send messages to a Slack channel');
    expect(line.lead).toBe('Nothing here does this.');
    expect(line.detail).toBe('Need a tool that can send messages to a Slack channel');
  });

  it('claims only the run when nobody described the gap', () => {
    // `every-workflow-green` 35: the door is now also opened by the *shape* of
    // a run — tools bound, none used — which cannot tell a refusal from a
    // knowledge answer. Past tense, because that is the whole of what the
    // shape proves: nothing here *did* this.
    const line = doorHeadline('');
    expect(line.lead).toBe('Nothing here did this.');
    expect(line.detail).toBe('Describe what you need.');
  });

  it('does not promise the catalogue is empty when it is only quiet', () => {
    // The present tense is a claim about the library and the shape cannot
    // support it. Getting this wrong is how a card teaches a developer to
    // distrust every card.
    expect(doorHeadline('   ').lead).not.toBe('Nothing here does this.');
  });

  it('treats whitespace as no description at all', () => {
    expect(doorHeadline('  \n ')).toEqual(doorHeadline(''));
  });
});
