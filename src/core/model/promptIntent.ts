/** Longest intent a card shows before eliding. */
const LIMIT = 160;

/**
 * Abbreviations and initialisms whose full stop does not end a sentence.
 *
 * Deliberately short. A general abbreviation dictionary is a research project
 * and the failure it prevents is cosmetic — a card line cut one word early —
 * while a wrong entry would truncate a legitimate sentence. These are the
 * forms that actually turn up in analytics and reporting prompts.
 */
const ABBREVIATIONS = /\b(?:[A-Z]\.[A-Z]|e\.g|i\.e|etc|vs|approx|no|fig|Dr|Mr|Ms|Mrs|St)\.$/i;

/**
 * The one line a card shows to say what an agent is for.
 *
 * **Derived, never authored.** The alternative was a second `does` field for
 * a developer to fill in, and a second field is a second thing that can
 * disagree with the prompt actually sent to the model. A well-written system
 * prompt already opens by saying what the agent is — every agent in the
 * shipped example does — so the first sentence is both free and incapable of
 * drifting from the truth.
 *
 * This exists because the prompt was invisible. `systemPrompt` is
 * `onCard: false`, which is right for a paragraph of rules, but the effect was
 * that a carefully instructed agent read on the canvas as an unconfigured
 * one — the owner looked at the analyst and asked whether the missing
 * instruction was deliberate. It was not; it was merely unshown.
 *
 * Returns `''` when there is nothing to say, so an unconfigured agent renders
 * no line at all rather than a placeholder that looks like a broken value.
 */
export function promptIntent(systemPrompt: string): string {
  const text = systemPrompt.trim();
  if (!text) return '';

  // A line break ends the intent as firmly as a full stop: prompts are often
  // a headline followed by a bulleted list, and the headline is the answer.
  const firstLine = text.split(/\r?\n/, 1)[0]?.trim() ?? '';
  if (!firstLine) return '';

  return truncate(firstSentence(firstLine));
}

function firstSentence(line: string): string {
  // Scan rather than split: `split(/[.!?]/)` cannot see what follows the
  // terminator, and what follows is the only way to tell `U.S. figures` from
  // the end of a sentence.
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character !== '.' && character !== '!' && character !== '?') continue;

    const next = line[index + 1];
    // Mid-word or mid-number: `0.5`, `gpt-4.1`. A terminator is only a
    // terminator when a space or the end of the line follows it.
    if (next !== undefined && next !== ' ' && next !== '\t') continue;

    const candidate = line.slice(0, index + 1);
    if (character === '.' && ABBREVIATIONS.test(candidate)) continue;

    return candidate;
  }
  return line;
}

function truncate(sentence: string): string {
  if (sentence.length <= LIMIT) return sentence;
  // Cut on a word boundary so the elision does not land mid-word.
  const cut = sentence.slice(0, LIMIT - 1);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > LIMIT / 2 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
