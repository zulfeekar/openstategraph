import { promptIntent } from '@core/model/promptIntent';
import type { NodeBodyProps } from './nodeBodyRegistry';
import './IntentBody.css';

/**
 * One line on a model-driven card saying what that node is for.
 *
 * The gap it closes was reported from live use as a design question — *"the
 * main agent after the text input does not have any skill saying what to do,
 * is that by choice?"* — and the answer was no: the analyst's agent carries a
 * careful system prompt, `systemPrompt` is `onCard: false`, and so a fully
 * instructed agent read on the canvas exactly like an empty one. Rules belong
 * in the inspector; *what this node is* belongs on the card.
 *
 * **Derived, not authored** (`promptIntent`): the first sentence of the text
 * that will actually be sent. A separate "description" field would be a second
 * thing to write and a second thing to fall out of step with the prompt, and a
 * card that confidently describes an agent doing something else is worse than
 * a card that says nothing.
 *
 * Read-only, and quiet. It borrows the composition annotation's type ramp and
 * colour so a Team's census line and an agent's intent line read as the same
 * kind of remark about a card rather than two inventions.
 *
 * Every family that drives a model shares this body — the same reasoning as
 * the shared model picker. Router and Grader keep their own text under
 * different keys, so the key is a parameter rather than a hardcoded
 * `systemPrompt`; a family that hardcoded it would silently show nothing.
 */
export function intentBody(fieldKey: string) {
  return function IntentBody({ node }: NodeBodyProps) {
    const intent = promptIntent(node.getField<string>(fieldKey) ?? '');
    if (!intent) return null;
    return (
      <div className="node__intent" title={intent}>
        {intent}
      </div>
    );
  };
}
