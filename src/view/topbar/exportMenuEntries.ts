import { FileJson, Image as ImageIcon, Upload } from 'lucide-react';
import type { MenuEntry } from '@design/primitives';
import type { WorkflowController } from '@controller/WorkflowController';
import type { PaperController } from '@canvas/PaperController';
import type { Workbench } from '@app/Workbench';
import {
  download,
  exportJSON,
  exportPNG,
  exportSVG,
  importJSON,
  slugify,
} from '@view/export/exportWorkflow';

interface ExportMenuDeps {
  readonly controller: WorkflowController;
  readonly paper: PaperController | null;
  readonly workbench: Workbench;
  readonly onNotify: (message: string) => void;
}

/**
 * What the toolbar's export control offers — `kanban-patrol/10`.
 *
 * Extracted from `TopBar` rather than left inline, and the reason is the one
 * `moduleSizeCeiling` asks for by name: this table has **its own reason to
 * change**. A new export format is a row here and nothing else; a change to
 * how the toolbar is laid out is the component and not this. They were one
 * module only because both happened to be needed in the same render.
 *
 * It stays a function of its four collaborators rather than a constant,
 * because every entry closes over the live controller, paper and document
 * name — a module-level constant would have to reach for them, which is the
 * global this codebase refuses elsewhere.
 */
export function exportMenuEntries({
  controller,
  paper,
  workbench,
  onNotify,
}: ExportMenuDeps): MenuEntry[] {
  return [
    {
      id: 'json',
      label: 'Workflow JSON',
      icon: FileJson,
      onSelect: () => exportJSON(controller),
    },
    {
      id: 'svg',
      label: 'Canvas as SVG',
      icon: ImageIcon,
      onSelect: () => {
        if (!paper) return;
        const svg = exportSVG(paper);
        if (!svg.ok) {
          onNotify(svg.error);
          return;
        }
        download(
          new Blob([svg.value], { type: 'image/svg+xml' }),
          `${slugify(workbench.model.name)}.svg`,
        );
      },
    },
    {
      id: 'png',
      label: 'Canvas as PNG',
      icon: ImageIcon,
      onSelect: () => {
        if (!paper) return;
        void exportPNG(paper).then((result) => {
          if (!result.ok) {
            onNotify(result.error);
            return;
          }
          download(result.value, `${slugify(workbench.model.name)}.png`);
        });
      },
    },
    { kind: 'separator', id: 'sep' },
    {
      id: 'import',
      label: 'Import JSON…',
      icon: Upload,
      onSelect: () =>
        // No fit here: replacing the document is framed by the canvas's own
        // `FrameOnLoadFeature`, which is why drilling into a mount — a path
        // that had no such hand-written call — used to lose the view.
        importJSON(controller, (outcome) => {
          if (outcome.message) onNotify(outcome.message);
        }),
    },
  ];
}
