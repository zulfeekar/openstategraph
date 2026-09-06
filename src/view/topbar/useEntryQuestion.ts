import { useEffect, useState } from 'react';
import { useController } from '@app/WorkbenchContext';
import { entryQuestion } from '@nodes/inputs/entryQuestion';

/**
 * The question Run would send, kept live as the canvas changes (ticket 03).
 *
 * Subscribed to the model's own events rather than polled or read once: the
 * Run button's disabled state has to react to the developer *typing* in the
 * Input node's field, and a field edit is a `node:data` event. `node:added`,
 * `node:removed` and `workflow:reset` matter too — deleting the only input
 * node, or opening a different workflow, changes the answer just as much.
 *
 * Every subscription is returned from the effect, so nothing outlives the
 * component.
 */
export function useEntryQuestion(): string {
  const controller = useController();
  const [question, setQuestion] = useState(() => entryQuestion(controller.model));

  useEffect(() => {
    const read = () => setQuestion(entryQuestion(controller.model));
    read();
    const offs = [
      controller.model.on('node:data', read),
      controller.model.on('node:added', read),
      controller.model.on('node:removed', read),
      controller.model.on('workflow:reset', read),
    ];
    return () => {
      for (const off of offs) off();
    };
  }, [controller]);

  return question;
}
