import { UNNAMED_DOCUMENT, isUnnamedDocument } from '@core/model/documentName';

/**
 * Who the thread says the left-hand messages are from — `stable-beta-public/10`.
 *
 * A conversation names its other side, and this product's other side is the
 * workflow the developer has open. Deliberately not an avatar and not a
 * generic word like "Assistant": the ticket's instruction was *do not invent
 * anything new*, and the product has no face for a workflow, while
 * "Assistant" would name something that does not exist — a run is this
 * document and no other.
 *
 * A document with no name still has a sender, so a blank falls back to the
 * word the top bar already shows for exactly this state (`UNNAMED_DOCUMENT`),
 * rather than to an empty label that would leave the first bubble of a run
 * unattributed. One owner for that word, in `core/`, so the two surfaces
 * cannot drift apart on what an unnamed document is called.
 */
export function senderLabel(documentName: string): string {
  return isUnnamedDocument(documentName) ? UNNAMED_DOCUMENT : documentName.trim();
}
