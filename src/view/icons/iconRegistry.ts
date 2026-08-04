import {
  Bot,
  FileCode2,
  FileText,
  Frame,
  MessagesSquare,
  StickyNote,
  Type,
  Wrench,
  Blocks,
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

  // Port types
  'port-text': Type,
  'port-skill': FileCode2,
  'port-tool': Wrench,
  'port-result': FileText,
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
