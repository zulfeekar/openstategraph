import { TEXT_INPUT_TYPE } from './TextInputNode';

/**
 * The minimum a caller must expose to be asked for its entry question.
 *
 * Structural rather than `WorkflowModel`, so the rule is unit-testable
 * without building a model and a registry — and so the only knowledge this
 * module carries is "an entry question lives in `input.text`'s `prompt`".
 */
export interface QuestionSource {
  nodes(): readonly { readonly type: string; getText(key: string): string }[];
}

/** The field an entry `Text Input` holds its prompt in. */
export const ENTRY_PROMPT_FIELD = 'prompt';

/**
 * What pressing Run would actually ask (ticket 03).
 *
 * The owner's rule: **the Input node's text field IS the question.** So Run
 * has exactly one honest source for what to send, and an empty one means
 * there is no question to run — which is what lets the button be truthfully
 * disabled instead of starting a run with nothing in it.
 *
 * Every `input.text` node counts, not just the first: `input.text` has no
 * inbound port, so every one of them is an entry, and a canvas with a prompt
 * *and* a style/context input would otherwise silently drop one. They are
 * joined in canvas order with a blank line, the same way a person would have
 * typed two paragraphs.
 *
 * Returns `''` when every entry input is blank — the disabled case.
 */
export function entryQuestion(source: QuestionSource): string {
  return source
    .nodes()
    .filter((node) => node.type === TEXT_INPUT_TYPE)
    .map((node) => node.getText(ENTRY_PROMPT_FIELD).trim())
    .filter((text) => text !== '')
    .join('\n\n');
}
