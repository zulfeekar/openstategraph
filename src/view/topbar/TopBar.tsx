import { useEffect, useState } from 'react';
import {
  Download,
  FileJson,
  Image as ImageIcon,
  KeyRound,
  Moon,
  MoveVertical,
  Network,
  PanelLeft,
  PanelRight,
  Play,
  Grid2x2,
  Redo2,
  Square,
  Sun,
  Undo2,
  Upload,
} from 'lucide-react';
import {
  Badge,
  Button,
  Icon,
  IconButton,
  Menu,
  Spinner,
  Tooltip,
  useMenu,
  shortcutText,
  type MenuEntry,
} from '@design/primitives';
import type { Theme } from '@design/tokens';
import {
  useController,
  useFlowDirection,
  useHistoryState,
  usePaperController,
  useWorkbench,
} from '@app/WorkbenchContext';
import { download, exportJSON, exportPNG, exportSVG, importJSON, slugify } from '@view/export/exportWorkflow';
import { RuntimeHealthDot } from './RuntimeHealthDot';
import './TopBar.css';

interface TopBarProps {
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  showGrid: boolean;
  onGridChange: (visible: boolean) => void;
  paletteOpen: boolean;
  onPaletteToggle: () => void;
  inspectorOpen: boolean;
  onInspectorToggle: () => void;
  onOpenCredentials: () => void;
  onNotify: (message: string) => void;
}

/**
 * The application toolbar.
 *
 * Grouped by what the controls act on — document, history, layout, then the
 * run action and the view/session controls on the right — rather than by
 * icon similarity. Run is the only filled button on screen, because it is
 * the only action that does something irreversible-feeling and the one a user
 * comes here to press.
 */
export function TopBar({
  theme,
  onThemeChange,
  showGrid,
  onGridChange,
  paletteOpen,
  onPaletteToggle,
  inspectorOpen,
  onInspectorToggle,
  onOpenCredentials,
  onNotify,
}: TopBarProps) {
  const workbench = useWorkbench();
  const flowDirection = useFlowDirection();
  const controller = useController();
  const paper = usePaperController();
  const { canUndo, canRedo } = useHistoryState();
  const exportMenu = useMenu<HTMLButtonElement>();

  const [running, setRunning] = useState(false);
  const [tokens, setTokens] = useState(0);

  useEffect(() => {
    const { engine } = workbench;
    const offStart = engine.on('run:start', () => {
      setRunning(true);
      setTokens(0);
    });
    const offUsage = engine.on('run:usage', ({ usage }) => setTokens(usage.totalTokens));
    const offFinish = engine.on('run:finish', ({ ok, error }) => {
      setRunning(false);
      if (!ok && error) onNotify(error);
    });
    return () => {
      offStart();
      offUsage();
      offFinish();
    };
  }, [workbench, onNotify]);

  const run = () => {
    if (running) {
      workbench.engine.cancel();
      return;
    }
    void workbench.engine.run();
  };

  const exportEntries: MenuEntry[] = [
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
        importJSON(controller, (outcome) => {
          if (outcome.message) onNotify(outcome.message);
          requestAnimationFrame(() => paper?.fitToContent());
        }),
    },
  ];

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__mark" aria-hidden="true">
          <Icon glyph={Network} size="md" />
        </span>
        <span className="topbar__product">Dyflow</span>
        <span className="topbar__divider" role="presentation" />
        <RuntimeHealthDot />
        <span className="topbar__doc" title={workbench.model.name}>
          {workbench.model.name}
        </span>
      </div>

      <div className="topbar__group">
        <Tooltip content="Toggle palette" shortcut={shortcutText('Mod+B')}>
          <IconButton
            label="Toggle palette"
            active={paletteOpen}
            icon={<Icon glyph={PanelLeft} size="md" />}
            onClick={onPaletteToggle}
          />
        </Tooltip>
        <Tooltip content="Toggle grid">
          <IconButton
            label="Toggle grid"
            active={showGrid}
            icon={<Icon glyph={Grid2x2} size="md" />}
            onClick={() => onGridChange(!showGrid)}
          />
        </Tooltip>

        <span className="topbar__divider" role="presentation" />

        <Tooltip content="Undo" shortcut={shortcutText('Mod+Z')}>
          <IconButton
            label="Undo"
            disabled={!canUndo}
            icon={<Icon glyph={Undo2} size="md" />}
            onClick={() => controller.history.undo()}
          />
        </Tooltip>
        <Tooltip content="Redo" shortcut={shortcutText('Mod+Shift+Z')}>
          <IconButton
            label="Redo"
            disabled={!canRedo}
            icon={<Icon glyph={Redo2} size="md" />}
            onClick={() => controller.history.redo()}
          />
        </Tooltip>

        <span className="topbar__divider" role="presentation" />

        <Tooltip content="Arrange automatically" multiline>
          <IconButton
            label="Arrange automatically"
            icon={<Icon glyph={Network} size="md" />}
            onClick={() => {
              paper?.autoLayout.run({
                rankDir: flowDirection === 'vertical' ? 'TB' : 'LR',
              });
              requestAnimationFrame(() => paper?.fitToContent());
            }}
          />
        </Tooltip>
        <Tooltip
          content={
            flowDirection === 'vertical'
              ? 'Flow direction: vertical — switch to horizontal'
              : 'Flow direction: horizontal — switch to vertical'
          }
          multiline
        >
          <IconButton
            label="Toggle flow direction"
            active={flowDirection === 'vertical'}
            icon={<Icon glyph={MoveVertical} size="md" />}
            onClick={() => {
              const next = flowDirection === 'vertical' ? 'horizontal' : 'vertical';
              workbench.preferences.setFlowDirection(next);
              // Re-arrange in the new direction so the toggle is visibly a
              // layout decision, not a hidden mode; one undoable transaction.
              requestAnimationFrame(() => {
                paper?.autoLayout.run({ rankDir: next === 'vertical' ? 'TB' : 'LR' });
                requestAnimationFrame(() => paper?.fitToContent());
              });
            }}
          />
        </Tooltip>
      </div>

      <div className="topbar__spacer" />

      <div className="topbar__group">
        {tokens > 0 ? (
          <Badge numeric tone={running ? 'accent' : 'neutral'}>
            {tokens.toLocaleString()} tokens
          </Badge>
        ) : null}

        <Tooltip content="API keys and endpoints" multiline>
          <IconButton
            label="API keys and endpoints"
            icon={<Icon glyph={KeyRound} size="md" />}
            onClick={onOpenCredentials}
          />
        </Tooltip>

        <Button
          variant={running ? 'secondary' : 'primary'}
          size="lg"
          icon={
            running ? <Spinner /> : <Icon glyph={Play} size="sm" strokeWidth={2.25} />
          }
          onClick={run}
        >
          {running ? 'Stop' : 'Run'}
        </Button>

        <Tooltip content="Export or import">
          <IconButton
            ref={exportMenu.anchorRef}
            label="Export or import"
            icon={<Icon glyph={Download} size="md" />}
            {...exportMenu.triggerProps}
          />
        </Tooltip>
        <Menu
          anchorRef={exportMenu.anchorRef}
          entries={exportEntries}
          open={exportMenu.open}
          onClose={exportMenu.close}
        />

        <Tooltip content={theme === 'dark' ? 'Light theme' : 'Dark theme'}>
          <IconButton
            label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            icon={<Icon glyph={theme === 'dark' ? Sun : Moon} size="md" />}
            onClick={() => onThemeChange(theme === 'dark' ? 'light' : 'dark')}
          />
        </Tooltip>

        <Tooltip content="Toggle inspector">
          <IconButton
            label="Toggle inspector"
            active={inspectorOpen}
            icon={<Icon glyph={PanelRight} size="md" />}
            onClick={onInspectorToggle}
          />
        </Tooltip>
      </div>
    </header>
  );
}

/** Re-exported so the shell can show the same glyph in its run affordances. */
export { Square as StopGlyph };
