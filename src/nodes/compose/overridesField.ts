import type { FieldSchema } from '@core/model/contracts/fields';

/**
 * The per-mount overrides field, shared by Team and Subgraph mounts
 * (docs/decisions/mount-overrides.md): JSON keyed by the child document's own
 * node ids — `{"grader1": {"criteria": "- stricter", "maxAttempts": 3}}`.
 * One definition, two mounts — the same class-vs-instance rule the feature
 * itself implements.
 *
 * Validation here covers only what the editor can know without the child
 * document (well-formed JSON, object-of-objects shape); unknown child node
 * ids are the runtime's job, which warns per run rather than blocking a save
 * against a package that may change underneath it.
 */
export const OVERRIDES_FIELD: FieldSchema = {
  kind: 'textarea',
  key: 'overrides',
  label: 'Overrides (this mount only)',
  placeholder: '{"grader1": {"criteria": "- stricter for this mount"}}',
  defaultValue: '',
  onCard: false,
  advanced: true,
  hint: 'JSON keyed by child node id. Other mounts keep the package defaults.',
  validate: (value: string) => {
    const raw = value.trim();
    if (!raw) return null;
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return 'Not valid JSON.';
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return 'Must be an object: {"<childNodeId>": {"<field>": value}}.';
    }
    for (const [nodeId, fields] of Object.entries(parsed)) {
      if (!fields || typeof fields !== 'object' || Array.isArray(fields)) {
        return `"${nodeId}" must map to an object of field values.`;
      }
    }
    return null;
  },
};
