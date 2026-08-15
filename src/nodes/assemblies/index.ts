import type { IAssemblyDefinition } from './contract';
import { revisionLoopAssembly } from './revisionLoop';
import { starterAssembly } from './starter';

export type { IAssemblyDefinition } from './contract';
export { REVISION_LOOP_ASSEMBLY_ID, revisionLoopAssembly } from './revisionLoop';
export { STARTER_ASSEMBLY_ID, starterAssembly } from './starter';

/**
 * The assemblies the palette offers — the public surface of this package.
 *
 * Two entries, and the second one arrived the way the first note said a second
 * one should: because somebody asked. Ticket 21 declined to build a general
 * "insert a wired assembly" mechanism up front and left a list so that adding
 * one would be a data change; ticket 22 is that data change.
 *
 * Order is reading order, and it is the beginner's order: the starter first,
 * because the palette entry that teaches the first flow should not sit below
 * the one that refines a flow you already have.
 */
export const ASSEMBLIES: readonly IAssemblyDefinition[] = [starterAssembly, revisionLoopAssembly];

/** The assembly a palette drag names, or `null` for an unknown id. */
export function assemblyById(id: string): IAssemblyDefinition | null {
  return ASSEMBLIES.find((assembly) => assembly.id === id) ?? null;
}
