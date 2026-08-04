import { GROUP } from '@design/tokens';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import { CATEGORY } from '../vocabulary';

const FIELD_TITLE = 'title';
const FIELD_NOTES = 'notes';

/**
 * A titled container that other nodes sit inside.
 *
 * `kind: 'container'` is what makes it embed children and stay out of the
 * execution schedule — the engine and the validator both key off the node
 * kind, so this class needs no run behaviour at all.
 *
 * The notes body renders above its children, which is why the container's
 * top padding is much larger than its other edges.
 */
export class GroupNodeModel extends AbstractNodeModel {
  get notes(): string {
    return this.getText(FIELD_NOTES);
  }

  override get title(): string {
    const explicit = this.getText(FIELD_TITLE).trim();
    return explicit.length > 0 ? explicit : this.definition.label;
  }
}

export const groupNode: INodeDefinition = defineNode(
  {
    id: 'annotate.group',
    kind: 'container',
    category: CATEGORY.annotate,
    label: 'Group',
    description: 'Frames related nodes together.',
    iconId: 'node-group',
    accent: 'blue',
    keywords: ['group', 'frame', 'container', 'panel', 'setup'],
    defaultSize: { width: 360, height: GROUP.minHeight + 80 },
    fields: [
      {
        kind: 'text',
        key: FIELD_TITLE,
        label: 'Title',
        placeholder: 'Group title',
        defaultValue: '',
      },
      {
        kind: 'textarea',
        key: FIELD_NOTES,
        label: 'Notes',
        placeholder: 'Markdown — steps, context, reminders…',
        defaultValue: '',
        minRows: 3,
      },
    ],
    ports: [],
  },
  GroupNodeModel,
);
