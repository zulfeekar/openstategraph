import {
  Bot,
  Database,
  FileCode2,
  FileText,
  Frame,
  MessagesSquare,
  StickyNote,
  Type,
  Wrench,
  Blocks,
  GitBranch,
  ShieldCheck,
  Split,
  Target,
  Users,
  FileOutput,
  UserCheck,
  Workflow,
  type LucideIcon,
} from 'lucide-react';

/**
 * Resolves the `iconId` tokens that node and port definitions carry.
 *
 * The model layer names icons as strings rather than importing glyphs,
 * because a node *definition* is data that gets serialized and must stay
 * free of React. This registry is where those names become components — the
 * one place that knows which icon set the app uses, so swapping icon
 * libraries is a change to this file alone.
 */
const ICONS: Record<string, LucideIcon> = {
  // Node families
  'node-text-input': Type,
  'node-markdown': FileCode2,
  'node-agent': Bot,
  'node-reddit': MessagesSquare,
  'node-output': FileText,
  'node-group': Frame,
  'node-note': StickyNote,
  // Chinook database nodes
  'node-database': Database,
  'node-router': GitBranch,
  'node-grader': ShieldCheck,
  'node-human-approval': UserCheck,
  'node-orchestrator': Split,
  'node-worker': Users,
  'node-format-report': FileOutput,
  'node-discovered-tool': Wrench,
  'node-subgraph': Workflow,
  // A Team is a mounted workflow that promises an outcome — so a target,
  // not a crowd. `Users` is already the Worker glyph, and reusing it here
  // would imply a headcount nothing verifies (ticket 02).
  'node-team': Target,
  'port-feedback': ShieldCheck,

  // Port types
  'port-text': Type,
  'port-skill': FileCode2,
  'port-tool': Wrench,
  'port-result': FileText,
  'port-worker': Users,
};

/** Shown when a definition names an icon this build doesn't have. */
const FALLBACK: LucideIcon = Blocks;

export function resolveIcon(iconId: string | undefined): LucideIcon {
  if (!iconId) return FALLBACK;
  return ICONS[iconId] ?? FALLBACK;
}

/** Lets a plugin contribute glyphs for its own node types. */
export function registerIcon(iconId: string, icon: LucideIcon): void {
  ICONS[iconId] = icon;
}
