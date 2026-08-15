import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import { CATEGORY } from '../vocabulary';

const FIELD_BODY = 'body';

/**
 * A free-floating Markdown note.
 *
 * `kind: 'annotation'` keeps it out of runs and out of validation, so a user
 * can leave commentary on a canvas without it counting as an unconnected
 * node or stalling the scheduler.
 */
export class NoteNodeModel extends AbstractNodeModel {
  get body(): string {
    return this.getText(FIELD_BODY);
  }

  override get title(): string {
    // First Markdown heading or first line, so the note names itself in the
    // inspector and the keyboard-navigation list.
    const firstLine = this.body.split('\n').find((line) => line.trim().length > 0) ?? '';
    const stripped = firstLine.replace(/^#{1,6}\s*/, '').trim();
    return stripped.length > 0 ? stripped.slice(0, 60) : this.definition.label;
  }
}

export const noteNode: INodeDefinition = defineNode(
  {
    id: 'annotate.note',
    kind: 'annotation',
    category: CATEGORY.annotate,
    label: 'Note',
    description: 'A Markdown note on the canvas.',
    iconId: 'node-note',
    accent: 'amber',
    keywords: ['note', 'comment', 'sticky', 'markdown', 'annotation', 'docs'],
    defaultSize: { width: 260, height: 160 },
    fields: [
      {
        kind: 'textarea',
        key: FIELD_BODY,
        label: 'Note',
        placeholder: 'Markdown supported…',
        defaultValue: '',
        minRows: 3,
        maxRows: 20,
      },
    ],
    ports: [],
  },
  NoteNodeModel,
);
