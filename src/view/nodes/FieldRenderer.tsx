import { useCallback, useEffect, useReducer, useRef, useState, type ChangeEvent } from 'react';
import { Replace } from 'lucide-react';
import type { ComboboxFieldSchema } from '@core/model/contracts/fields';
import {
  Badge,
  Button,
  DisplayRow,
  Field,
  Select,
  Slider,
  TextArea,
  TextInput,
  useFieldId,
  type SelectOption,
} from '@design/primitives';
import {
  nextRowId,
  resolveOptions,
  type FieldSchema,
  type FieldValue,
  type NodeData,
  type RepeatableGroupSchema,
  type RowVerdict,
} from '@core/model/contracts/fields';
import type { NodeId } from '@core/model/contracts/node';
import { useController } from '@app/WorkbenchContext';

interface FieldRendererProps {
  nodeId: NodeId;
  schema: FieldSchema;
  data: Readonly<NodeData>;
  /** Field-level error from workflow validation. */
  error?: string;
}

/**
 * Renders one schema-declared field as a design-system control.
 *
 * This is the payoff of declaring node configuration as data: node types
 * describe their fields once, and both the card and the inspector render
 * them from the same switch. A new field *kind* is a case here; a new
 * *field* on an existing node type needs no view code at all.
 *
 * Every control is wrapped in `data-no-drag`, which the paper's guard uses to
 * let a pointer-down reach the control instead of starting a node drag —
 * without it, dragging a slider would move the node.
 */
export function FieldRenderer({ nodeId, schema, data, error }: FieldRendererProps) {
  const controller = useController();
  const id = useFieldId('field-');

  const set = useCallback(
    (value: FieldValue) => controller.nodes.setField(nodeId, schema.key, value),
    [controller, nodeId, schema.key],
  );

  // Inherited-vs-overridden, in the one place every field is rendered
  // (ticket 42, tranche 5). Before this, a mount's own values were real but
  // invisible: the only way to see or author one was a JSON textarea keyed by
  // child node ids you had to know by heart.
  const mounts = controller.document.mountContext();
  const overridden = mounts?.isOverridden(nodeId, schema.key) ?? false;
  const revert = useCallback(
    () => controller.nodes.clearOverride(nodeId, schema.key),
    [controller, nodeId, schema.key],
  );

  const common = {
    label: schema.label,
    ...(overridden
      ? {
          labelValue: (
            <button
              type="button"
              className="field__override"
              // The package's own value, so the badge answers "what would I
              // get back" without a second click. `knowsInherited` is false
              // when the inherited document could not be fetched, and then
              // this must not claim a default it does not have.
              title={
                mounts?.knowsInherited
                  ? `This mount overrides the package. Click to use the package default: ${String(
                      mounts.inheritedValue(nodeId, schema.key) ?? '(empty)',
                    ).slice(0, 120)}`
                  : 'This mount overrides the package.'
              }
              disabled={!mounts?.knowsInherited}
              onClick={revert}
            >
              overridden
            </button>
          ),
        }
      : {}),
    ...(schema.hint ? { hint: schema.hint } : {}),
    ...(error ? { error } : {}),
    htmlFor: id,
  };

  switch (schema.kind) {
    case 'text': {
      const value = asString(data[schema.key]);
      return (
        <Field {...common}>
          <div data-no-drag>
            <TextInput
              id={id}
              value={value}
              placeholder={schema.placeholder}
              maxLength={schema.maxLength}
              mono={schema.mono}
              invalid={Boolean(error)}
              prefix={schema.prefix}
              suffix={schema.suffix}
              onChange={(event) => set(event.target.value)}
            />
          </div>
        </Field>
      );
    }

    case 'textarea': {
      const value = asString(data[schema.key]);
      return (
        <Field {...common}>
          <div data-no-drag>
            <TextArea
              id={id}
              value={value}
              placeholder={schema.placeholder}
              minRows={schema.minRows}
              maxRows={schema.maxRows}
              maxLength={schema.maxLength}
              mono={schema.mono}
              invalid={Boolean(error)}
              onChange={(event) => set(event.target.value)}
            />
          </div>
        </Field>
      );
    }

    case 'select': {
      const options = resolveOptions(schema, data).map<SelectOption>((option) => ({
        value: option.value,
        label: option.label,
        ...(option.group ? { group: option.group } : {}),
        ...(option.disabled ? { disabled: true } : {}),
      }));
      const value = asString(data[schema.key]) || schema.defaultValue;
      return (
        <Field {...common}>
          <div data-no-drag>
            <Select id={id} options={options} value={value} onValueChange={set} />
          </div>
        </Field>
      );
    }

    case 'combobox': {
      return (
        <Field {...common}>
          <ComboboxField
            id={id}
            schema={schema}
            value={asString(data[schema.key])}
            data={data}
            onChange={set}
          />
        </Field>
      );
    }

    case 'slider': {
      const value = asNumber(data[schema.key], schema.defaultValue);
      return (
        <Field {...common} labelValue={schema.format ? schema.format(value) : `· ${value}`}>
          <div data-no-drag>
            <Slider
              id={id}
              value={value}
              min={schema.min}
              max={schema.max}
              step={schema.step ?? 1}
              // Live updates keep the readout responsive; only the commit
              // records an undo entry, so a drag is one step.
              onValueChange={(next) => set(next)}
              onValueCommit={(next) => set(next)}
            />
          </div>
        </Field>
      );
    }

    case 'toggle': {
      const value = asBoolean(data[schema.key], schema.defaultValue);
      return (
        <Field {...common}>
          <div data-no-drag>
            <Button active={value} onClick={() => set(!value)}>
              {value ? 'On' : 'Off'}
            </Button>
          </div>
        </Field>
      );
    }

    case 'file':
      return <FileField nodeId={nodeId} schema={schema} data={data} labelId={id} />;

    case 'readonly': {
      // The schema, not the node. This prose is identical for every node of
      // the type, so it is declared once and shown from there — and since
      // ticket 52 it is deliberately absent from `data`, where a copy of it
      // was being written into the user's `workflow.json`. `data` is still
      // yet re-saved, renders the same — `defaultValue` is required on this
      // kind, so the fallback only ever fires for an empty declaration.
      const value = asString(schema.defaultValue) || asString(data[schema.key]);
      return (
        <Field {...common}>
          <DisplayRow value={value || '—'} />
        </Field>
      );
    }

    case 'repeatable-group': {
      const value = data[schema.key];
      const rows = Array.isArray(value) ? (value as Array<Record<string, FieldValue>>) : [];
      return <RepeatableGroupField nodeId={nodeId} schema={schema} rows={rows} {...common} />;
    }
  }
}

/**
 * File picker.
 *
 * Reads the file's text immediately and writes name and content in one
 * command, so undo restores both together — a half-loaded file (name set,
 * content stale) would silently run the wrong instruction.
 */
function FileField({
  nodeId,
  schema,
  data,
  labelId,
}: {
  nodeId: NodeId;
  schema: Extract<FieldSchema, { kind: 'file' }>;
  data: Readonly<NodeData>;
  labelId: string;
}) {
  const controller = useController();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const filename = asString(data[schema.key]);

  const onPick = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    controller.nodes.setFields(
      nodeId,
      { [schema.key]: file.name, [schema.contentKey]: text },
      `Load ${file.name}`,
    );
    // Clear the input so re-picking the same file fires a change event.
    event.target.value = '';
  };

  return (
    <Field label={schema.label} htmlFor={labelId}>
      <div data-no-drag>
        <DisplayRow
          value={filename || 'No file selected'}
          action={
            <Button
              size="sm"
              onClick={() => inputRef.current?.click()}
              icon={filename ? undefined : <Replace size={12} strokeWidth={1.75} />}
            >
              {schema.actionLabel ?? (filename ? 'Replace' : 'Choose')}
            </Button>
          }
        />
        <input
          ref={inputRef}
          id={labelId}
          type="file"
          accept={schema.accept}
          className="sr-only"
          onChange={(event) => void onPick(event)}
        />
      </div>
    </Field>
  );
}

const asString = (value: FieldValue | undefined): string =>
  typeof value === 'string' ? value : '';

const asNumber = (value: FieldValue | undefined, fallback: number): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

const asBoolean = (value: FieldValue | undefined, fallback: boolean): boolean =>
  typeof value === 'boolean' ? value : fallback;

/**
 * A row field's own validator, applied to that row's value.
 *
 * `validate` is declared on the value-bearing schemas rather than on a group
 * of them, so the union has to be narrowed to reach it — the same switch the
 * app-level MCP panel runs, deliberately, because a row that accepted what the
 * flat field refuses would be a second answer to "is this a variable name or
 * the credential itself".
 */
function rowError(field: FieldSchema, value: FieldValue | undefined): string | undefined {
  switch (field.kind) {
    case 'text':
    case 'textarea':
    case 'select':
    case 'combobox':
    case 'file':
    case 'readonly':
      return field.validate?.(asString(value)) ?? undefined;
    default:
      return undefined;
  }
}

/**
 * Repeatable group field — a list of rows, each with stable ids.
 *
 * Used for router branches: each row has {id, name} where id is generated
 * once and survives renames, so edges referencing `branch:${id}` don't
 * break when the user renames a branch. Since mcp-connect ticket 04 it also
 * carries whole sub-records — one MCP server per row — which is what put a
 * validator and an optional per-row probe on rows that had neither.
 */
function RepeatableGroupField({
  nodeId,
  schema,
  rows,
  ...common
}: {
  nodeId: NodeId;
  schema: RepeatableGroupSchema;
  rows: Array<Record<string, FieldValue>>;
  label?: string;
  hint?: string;
  error?: string;
  htmlFor: string;
}) {
  const controller = useController();
  /** Verdicts by row id — `null` while a probe is in flight. */
  const [verdicts, setVerdicts] = useState<Record<string, RowVerdict | null>>({});

  const probe = schema.rowProbe;
  const check = (key: string, row: Record<string, FieldValue>) => {
    if (!probe) return;
    setVerdicts((current) => ({ ...current, [key]: null }));
    void probe.run(row).then((verdict) => {
      setVerdicts((current) => ({ ...current, [key]: verdict }));
    });
  };

  const addRow = () => {
    const newRow: Record<string, FieldValue> = {};
    for (const field of schema.fields) {
      newRow[field.key] = field.defaultValue ?? null;
    }
    // Generate a stable id for new rows — through the one generator, so the
    // card and the app-level panel cannot mint them differently, and so two
    // rows added in the same millisecond cannot collide (ticket 52).
    if (!newRow.id) {
      newRow.id = nextRowId();
    }
    const nextRows = [...rows, newRow];
    controller.nodes.setField(nodeId, schema.key, nextRows);
  };

  const removeRow = (index: number) => {
    const nextRows = rows.filter((_, i) => i !== index);
    controller.nodes.setField(nodeId, schema.key, nextRows);
  };

  const updateRow = (index: number, key: string, value: FieldValue) => {
    const nextRows = rows.map((row, i) => (i === index ? { ...row, [key]: value } : row));
    controller.nodes.setField(nodeId, schema.key, nextRows);
  };

  const canAdd = schema.maxRows === undefined || rows.length < schema.maxRows;

  return (
    <Field {...common}>
      <div data-no-drag>
        <div className="repeatable-group">
          {rows.map((row, index) => {
            const rowKey = (row.id as string) ?? String(index);
            const verdict = rowKey in verdicts ? verdicts[rowKey] : undefined;
            return (
              <div key={rowKey} className="repeatable-group__row">
                {schema.fields.map((field) => {
                  // The schema's own validator, run where the schema declared
                  // it — the same function the app-level panel runs. Without
                  // this a row could accept what the flat field refuses, and
                  // the field it refuses is the one holding a credential.
                  const invalid = rowError(field, row[field.key]);
                  return (
                    <div key={field.key} className="repeatable-group__field">
                      {/* Named, since ticket 26. Three unlabelled controls in a
                      row is a puzzle: the Guardrail card showed a combobox, a
                      select and a monospace box side by side and never said
                      which was the entity, which the strategy and which the
                      pattern. */}
                      {field.label ? (
                        <span className="repeatable-group__label">{field.label}</span>
                      ) : null}
                      {field.kind === 'text' && (
                        <TextInput
                          value={asString(row[field.key])}
                          placeholder={field.placeholder}
                          invalid={Boolean(invalid)}
                          onChange={(e) => updateRow(index, field.key, e.target.value)}
                          mono={field.mono}
                        />
                      )}
                      {field.kind === 'textarea' && (
                        <TextArea
                          value={asString(row[field.key])}
                          placeholder={field.placeholder}
                          minRows={field.minRows}
                          maxRows={field.maxRows}
                          onChange={(e) => updateRow(index, field.key, e.target.value)}
                          mono={field.mono}
                        />
                      )}
                      {/* A row's combobox rendered **nothing at all** until ticket
                      26 — the case was simply missing from this list, so the
                      Guardrail's Entity control was an empty gap on the card
                      and a rule could not be told what it was about. Same
                      datalist component the switch above uses, so the two
                      cannot drift. */}
                      {field.kind === 'combobox' && (
                        <ComboboxField
                          id={`${common.htmlFor}-${index}-${field.key}`}
                          schema={field}
                          value={asString(row[field.key])}
                          data={row}
                          onChange={(val) => updateRow(index, field.key, val)}
                        />
                      )}
                      {field.kind === 'select' && (
                        <Select
                          options={resolveOptions(field, row).map((opt) => ({
                            value: opt.value,
                            label: opt.label,
                            group: opt.group,
                            disabled: opt.disabled,
                          }))}
                          value={asString(row[field.key]) || field.defaultValue}
                          onValueChange={(val) => updateRow(index, field.key, val)}
                        />
                      )}
                      {/* Missing for the same reason `combobox` was: the Grader's
                      rubric rows declare a `required` toggle that has never
                      rendered. */}
                      {field.kind === 'toggle' && (
                        <Button
                          active={asBoolean(row[field.key], field.defaultValue)}
                          onClick={() =>
                            updateRow(
                              index,
                              field.key,
                              !asBoolean(row[field.key], field.defaultValue),
                            )
                          }
                        >
                          {asBoolean(row[field.key], field.defaultValue) ? 'On' : 'Off'}
                        </Button>
                      )}
                      {invalid ? <span className="repeatable-group__error">{invalid}</span> : null}
                    </div>
                  );
                })}
                {probe ? (
                  <div className="repeatable-group__probe">
                    <Button
                      size="sm"
                      disabled={verdict === null}
                      onClick={() => check(rowKey, row)}
                    >
                      {verdict === null ? 'Checking…' : probe.label}
                    </Button>
                    {verdict ? (
                      <Badge tone={verdict.ok ? 'success' : 'danger'}>{verdict.label}</Badge>
                    ) : null}
                  </div>
                ) : null}
                {verdict?.detail ? (
                  <p className="repeatable-group__detail">{verdict.detail}</p>
                ) : null}
                <button
                  type="button"
                  onClick={() => removeRow(index)}
                  className="repeatable-group__remove"
                  aria-label="Remove row"
                >
                  ×
                </button>
              </div>
            );
          })}
          {canAdd && (
            <button type="button" onClick={addRow} className="repeatable-group__add">
              + {schema.addLabel}
            </button>
          )}
        </div>
      </div>
    </Field>
  );
}

/**
 * A text box with suggestions, subscribed to the source of those suggestions.
 *
 * Its own component because it needs a hook: a suggestion list arrives over
 * HTTP and moves when a package is saved or a server registered, and a `case`
 * in the switch above cannot call `useSyncExternalStore` — hooks may not be
 * conditional. Extracting it is also what lets the subscription be *narrow*:
 * only the field whose store moved re-renders, not every field on the
 * inspector.
 *
 * **The field names its own store.** This used to subscribe to
 * `workflowCatalogue` by name, so the MCP server picker — the second live
 * combobox — could not be given a live list without editing this file
 * (mcp-connect ticket 07). A schema declaring `subscribe` extends the renderer
 * by registering rather than by editing it.
 */
function ComboboxField({
  id,
  schema,
  value,
  data,
  onChange,
}: {
  id: string;
  schema: ComboboxFieldSchema;
  /** The current text. Passed in rather than read out of `data`, because a
   *  repeatable-group row holds its value in the row, not on the node. */
  value: string;
  /** What the options are resolved against — the node's data, or the row's. */
  data: Readonly<NodeData> | Readonly<Record<string, FieldValue>>;
  onChange: (value: string) => void;
}) {
  // A schema is data assembled once at import time, so `subscribe` is stable;
  // keying the effect on it anyway means a field that swapped stores would
  // resubscribe rather than keep listening to the old one.
  const subscribe = schema.subscribe;
  const [, redraw] = useReducer((count: number) => count + 1, 0);
  useEffect(() => subscribe?.(redraw), [subscribe]);

  // A native `<datalist>`: the browser gives the dropdown, the filtering and
  // the keyboard handling, and the control stays a plain text input — so the
  // value written is the same string a free-text box wrote, which is the
  // constraint (`data.workflow` is a serialised contract).
  const options = resolveOptions(schema, data);
  const listId = `${id}-options`;
  return (
    <div data-no-drag>
      <TextInput
        id={id}
        list={listId}
        mono={schema.mono}
        value={value}
        placeholder={schema.placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      <datalist id={listId}>
        {options.map((option) => (
          <option key={option.value} value={option.value} label={option.label} />
        ))}
      </datalist>
      {options.length === 0 && schema.emptyHint ? (
        <p className="field__hint">{schema.emptyHint}</p>
      ) : null}
    </div>
  );
}
