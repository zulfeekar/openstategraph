import { describe, expect, it } from 'vitest';
import { promptIntent } from './promptIntent';

describe('promptIntent', () => {
  it('takes the first sentence — a well-written prompt opens by saying what it is', () => {
    // Verbatim from workflows/chinook-assistant, the two agents whose cards
    // read as unconfigured before this existed.
    expect(
      promptIntent(
        'You are the front desk of an assistant whose speciality is the Chinook ' +
          'music-store database. You hold no tools and no database access.',
      ),
    ).toBe(
      'You are the front desk of an assistant whose speciality is the Chinook music-store database.',
    );
    expect(
      promptIntent('You answer questions that need the live web.\n\nAlways work in this order:'),
    ).toBe('You answer questions that need the live web.');
  });

  it('stops at a line break even when no full stop arrived', () => {
    expect(promptIntent('Route on what the message NEEDS\n- data_query — ...')).toBe(
      'Route on what the message NEEDS',
    );
  });

  it('is empty for an unconfigured agent, so the card shows nothing rather than a stub', () => {
    expect(promptIntent('')).toBe('');
    expect(promptIntent('   \n  ')).toBe('');
  });

  it('does not split an abbreviation or a decimal into a sentence', () => {
    expect(promptIntent('Answer using the U.S. figures only. Then stop.')).toBe(
      'Answer using the U.S. figures only.',
    );
    expect(promptIntent('Round to 0.5 of a percent. Never guess.')).toBe(
      'Round to 0.5 of a percent.',
    );
  });

  it('caps a run-on first sentence rather than letting it fill the card', () => {
    const long = `You are ${'very '.repeat(60)}helpful.`;
    const intent = promptIntent(long);
    expect(intent.length).toBeLessThanOrEqual(160);
    expect(intent.endsWith('…')).toBe(true);
  });

  it('keeps a question or an exclamation as the sentence it is', () => {
    expect(promptIntent('Are the figures cited? Check every one.')).toBe('Are the figures cited?');
  });
});
