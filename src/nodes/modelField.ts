import type { SelectFieldSchema } from '@core/model/contracts/fields';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';
import { MOCK_SELECTION, workflowModelAsSelection } from '@core/providers/modelSelection';

// The two spellings of "which model" moved to `core/providers` when the
// registry itself had to resolve the document's default. Re-exported here so
// a node family keeps importing them from the field it configures.
export { MOCK_SELECTION, workflowModelAsSelection };

/** The key the backend's `_resolve_model(data)` reads. One spelling, shared. */
export const MODEL_FIELD_KEY = 'model';

/**
 * The empty selection: "whatever model this workflow runs on".
 *
 * Empty string rather than a sentinel word, because empty is what
 * `_resolve_model` already treats as "no override" (`if not selection: return
 * self.model`). The UI is being taught to say what the backend has always
 * done, not given a new state to serialise.
 */
export const WORKFLOW_DEFAULT_MODEL = '';

/**
 * The model picker, declared **once** for every node family that drives a
 * model.
 *
 * This exists because the shared concern had drifted the other way. The
 * backend's `NodeRuntime._resolve_model(data)` reads `data["model"]` for
 * agents, routers, graders, orchestrators, workers and format-report nodes —
 * and its own docstring claimed "the same select `RouterNode.ts`/
 * `GraderNode.ts` use". They did not: only `agent.llm` ever shipped the
 * field. Five node types drove a model with no way to choose it, and the
 * backend was reading a key nothing could write. So the fix is not five
 * copies of a select; it is one descriptor the families import, in the same
 * shape as `OVERRIDES_FIELD` — CLAUDE.md's rule that a shared concern is
 * declared once and never re-declared per concrete type.
 *
 * A factory rather than a constant because the option list depends on the
 * `ProviderRegistry` — which providers exist and which hold credentials — and
 * that is runtime state, not a literal.
 *
 * **The default is the workflow's model.** It used to be
 * `selectionFor('mock', 'mock-offline')`, which made every unconfigured card
 * read *Mock · Offline* while the run used the real shared model, because
 * `_resolve_model` maps `mock` to "no override" just as it maps empty. The
 * card named a fake model for a node that would use a real one — the owner
 * read exactly that off the canvas and asked why the Concierge and the Web
 * Researcher were offline. Mock remains selectable: it is a genuine
 * frontend-only deterministic simulator for the local canvas preview, and
 * choosing it deliberately is different from landing on it by default.
 */
/**
 * The selection a node with no override should actually run.
 *
 * One function so the browser's preview executors resolve "workflow default"
 * exactly as `NodeRuntime._resolve_model` does on the backend: the node's own
 * choice, else the workflow's, else — and only in the browser — the mock
 * simulator. That last step is not a fallback the backend has or wants: the
 * server always holds a real configured model, while the canvas preview is a
 * deterministic offline simulator by design and has no key to reach anything
 * real. Naming that here keeps the difference in one readable place instead
 * of leaving each executor to invent it.
 */
export function resolveModelSelection(
  nodeSelection: string,
  workflowSettings: Readonly<Record<string, unknown>>,
): string {
  const own = nodeSelection.trim();
  if (own) return own;
  const shared = workflowSettings['model'];
  if (typeof shared === 'string' && shared.trim()) {
    return workflowModelAsSelection(shared.trim());
  }
  return MOCK_SELECTION;
}

export function modelField(providers: ProviderRegistry): SelectFieldSchema {
  return {
    kind: 'select',
    key: MODEL_FIELD_KEY,
    label: 'Model',
    // Resolved lazily on each render so a key added mid-session, or a freshly
    // pulled Ollama model, shows up without a reload.
    options: () => [
      {
        value: WORKFLOW_DEFAULT_MODEL,
        label: 'Workflow default',
        // Its own group, so it never sorts into a vendor's list and never
        // reads as one more model somebody has to have heard of.
        group: 'This workflow',
      },
      ...providers.modelOptions(),
    ],
    defaultValue: WORKFLOW_DEFAULT_MODEL,
    hint: 'Leave on the workflow default unless this step needs a different model.',
  };
}
