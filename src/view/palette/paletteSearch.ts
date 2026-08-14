import { matchesQuery } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import { ASSEMBLIES, type IAssemblyDefinition } from '@nodes/assemblies/revisionLoop';

/**
 * Assemblies belonging to one palette section, filtered by the search box.
 *
 * Hidden entirely while searching unless they match — a filtered palette is a
 * lookup, and an entry that ignores the filter reads as a bug.
 */
export function assembliesFor(categoryId: string, query: string): readonly IAssemblyDefinition[] {
  const needle = query.trim().toLowerCase();
  return ASSEMBLIES.filter((assembly) => assembly.category === categoryId).filter(
    (assembly) =>
      !needle ||
      assembly.label.toLowerCase().includes(needle) ||
      assembly.keywords.some((keyword) => keyword.includes(needle)),
  );
}

/**
 * Whether a palette section still has anything to show for this search.
 *
 * **A section survives on nodes *or* assemblies**, and the `or` is the whole
 * point. The rule used to be nodes alone, applied twice — once when filtering
 * sections and again when collecting them — so a section whose only match was
 * an assembly was dropped, twice, before its assemblies were ever consulted.
 *
 * The victim was the Revision loop. No *node type* matches "loop", "revise" or
 * "retry", so those three searches returned nothing at all — and they are
 * precisely the words somebody looking for a revision loop types. The one item
 * in the palette that is hard to discover by browsing (26th of 28, below the
 * fold at a narrow width) was also the one item search could not find.
 *
 * Pure and separate from `Palette.tsx` so this is testable without React: the
 * component renders the answer, it does not own the rule.
 */
export function sectionSurvivesSearch(
  section: { readonly category: { readonly id: string }; readonly nodes: readonly INodeDefinition[] },
  query: string,
): boolean {
  if (!query.trim()) return true;
  return (
    section.nodes.some((definition) => matchesQuery(definition, query)) ||
    assembliesFor(section.category.id, query).length > 0
  );
}
