import { continuingThread, rememberThread, type ThreadBinding } from './thread';

/**
 * One conversation per open workflow, held where a panel cannot take it with
 * it — `memory-and-replay` 35.
 *
 * The defect this exists to remove: the thread was `useState` inside
 * `AskPanel`, and the Ask panel is *conditionally rendered*, so closing it is
 * a real unmount. A developer who typed into the canvas' Input node, pressed
 * Run, read the answer on the canvas, closed the panel and ran again was
 * starting a fresh conversation every time — measured, `thread_id: null` on
 * the second send — while nothing on screen said so. The editor had one
 * memory and two doors, and the memory belonged to one of them.
 *
 * So the thread is not panel state, and neither is the transcript. They move
 * together on purpose: a thread restored without the turns that filled it is
 * an answer with an antecedent the developer cannot see, which is a worse bug
 * than the one being fixed and a much quieter one. `AskPanel`'s own docblock
 * argued exactly that against persisting the id alone, and it was right —
 * what was wrong was concluding that continuity therefore had to end at the
 * panel's edge.
 *
 * **In memory, for this tab, for this load.** Not `localStorage`, not
 * `sessionStorage`: the two reasons `AskPanel` gives still stand — this is an
 * editor, a reload usually follows an edit to the document or to a workflow's
 * `tools/`, and the checkpointed `messages` belong to the graph as it was.
 * Surviving a reload is `production-ready` 90's question, asked of the
 * transcript rather than of the thread, and this store is where it would be
 * answered.
 *
 * ## The subject is an address, never a class slug
 *
 * Keyed by what `openSubject` names — `concierge/wf-music`, not
 * `chinook-assistant`. `production-ready` 07 proved these are different
 * strings and that confusing them empties a canvas; here the same confusion
 * would pour two mounts of one package into a single conversation and replay
 * one instance's history into the other. The class slug is still carried
 * beside the id, because the checkpointer is keyed by thread id **alone** and
 * `thread.ts` states the case: a conversation about a different graph is a
 * different conversation.
 */
export interface Conversation<TTurn> {
  /** The server-named thread the next question continues, or `null`. */
  readonly thread: ThreadBinding | null;
  /** What the panel has shown for this subject, newest last. */
  readonly turns: readonly TTurn[];
}

/**
 * The one subject key an unsaved canvas gets.
 *
 * Two unsaved canvases are indistinguishable here — the same resolution the
 * run itself has, so nothing new is lost (`ThreadBinding`).
 */
const UNSAVED = '';

export class ConversationStore<TTurn> {
  readonly #bySubject = new Map<string, Conversation<TTurn>>();
  readonly #listeners = new Set<() => void>();
  readonly #empty: Conversation<TTurn> = { thread: null, turns: [] };

  /**
   * What is held for `subject` — the same object until something changes, so
   * a React subscriber can compare snapshots by identity.
   */
  read(subject: string | null): Conversation<TTurn> {
    return this.#bySubject.get(subject ?? UNSAVED) ?? this.#empty;
  }

  /**
   * The `thread_id` a question asked against `slug` under `subject` should
   * carry, or `undefined` to let the server open a conversation.
   */
  continuing(subject: string | null, slug: string | undefined): string | undefined {
    return continuingThread(this.read(subject).thread, slug);
  }

  /** Fold a terminal frame's disclosed thread id into what is held. */
  remember(subject: string | null, slug: string | undefined, threadId: string): void {
    this.#write(subject, (held) => ({
      ...held,
      thread: rememberThread(held.thread, slug, threadId),
    }));
  }

  /** Replace the transcript, in the functional shape `setTurns` already had. */
  setTurns(
    subject: string | null,
    updater: (turns: readonly TTurn[]) => readonly TTurn[],
  ): readonly TTurn[] {
    return this.#write(subject, (held) => ({ ...held, turns: updater(held.turns) })).turns;
  }

  /**
   * Start over: the next question from **either** door opens a new
   * conversation.
   *
   * Forgetting the thread is the whole of it — the transcript stays, for the
   * reason `AskPanel`'s New control has always kept it: a run's trace is
   * evidence, and a button that silently deleted it would make "start a new
   * conversation" and "throw away what the last one showed me" one gesture.
   */
  newSession(subject: string | null): void {
    this.#write(subject, (held) => ({ ...held, thread: null }));
  }

  /** Told after storage has settled, never before. */
  subscribe(listener: () => void): () => void {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  }

  #write(
    subject: string | null,
    change: (held: Conversation<TTurn>) => Conversation<TTurn>,
  ): Conversation<TTurn> {
    const key = subject ?? UNSAVED;
    const next = change(this.read(subject));
    this.#bySubject.set(key, next);
    for (const listener of this.#listeners) listener();
    return next;
  }
}
