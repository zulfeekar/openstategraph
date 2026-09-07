/**
 * The two spellings of "which model", and the one conversion between them.
 *
 * Lives beside the registry rather than with the node field because the
 * registry is what resolves a selection, and it now has to resolve the
 * document's default too. `modelField.ts` re-exports both names, so a node
 * family still imports them from the field it configures.
 */

/** The offline simulator the local canvas preview falls back to. */
export const MOCK_SELECTION = 'mock/mock-offline';

/**
 * `settings.model` → a selection this registry can resolve.
 *
 * **The two strings are not the same format, and every shipped workflow
 * proves it**: `workflow.settings.model` reads `ollama:gpt-oss:120b-cloud`,
 * because that is what `init_chat_model` wants and settings are written for
 * the runtime; a node's own field reads `ollama/gpt-oss:120b-cloud`, because
 * `ProviderRegistry.selectionFor` separates with a slash. Colon-separated,
 * `resolve()` finds no slash, then looks for a model *literally* called
 * `ollama:gpt-oss:120b-cloud`, finds none, and the preview reports "Unknown
 * model" for a workflow that runs perfectly on the backend.
 *
 * Only the **first** colon separates: a model id may contain its own
 * (`gpt-oss:120b-cloud`), and splitting on the last would invent a provider
 * called `ollama:gpt-oss`. A value that already carries a slash is a
 * selection and is returned untouched.
 */
export function workflowModelAsSelection(settingsModel: string): string {
  if (settingsModel.includes('/')) return settingsModel;
  const separator = settingsModel.indexOf(':');
  if (separator <= 0) return settingsModel;
  return `${settingsModel.slice(0, separator)}/${settingsModel.slice(separator + 1)}`;
}
