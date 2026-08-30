import { describe, expect, it } from 'vitest';
import { waitingLine, WAITING_TO_START, WAITING_FOR_THE_NEXT_STEP } from './waitingLine';

const base = {
  running: true,
  saidSomething: false,
  streaming: false,
  awaitingApproval: false,
  stepsSoFar: 0,
};

describe('waitingLine', () => {
  it('names the wait before any frame has arrived', () => {
    expect(waitingLine(base)).toBe(WAITING_TO_START);
  });

  it('names the wait once steps have finished but nothing has spoken', () => {
    // The measured case (launch-readiness/141): on a 28-node package the wire
    // carries `in1` at 0.06 s and `router1` at 2.16 s, and the first
    // narration frame does not leave the server until 4.99 s.
    expect(waitingLine({ ...base, stepsSoFar: 2 })).toBe(WAITING_FOR_THE_NEXT_STEP);
  });

  it('says nothing once a step is narrating itself', () => {
    // `launch-readiness/110`: a placeholder that outlives the real line is the
    // same defect as a real line that erases itself.
    expect(waitingLine({ ...base, stepsSoFar: 2, saidSomething: true })).toBeNull();
  });

  it('belongs to the opening silence only, once a step has ever spoken', () => {
    // Measured live on `/chat` before this rule: the placeholder appeared and
    // vanished inside a millisecond three times between 7.9 s and 12.3 s of
    // one run, because narration is cleared by its own step completing and
    // the wait then looked fresh again. A placeholder that blinks is worse
    // than the gap it fills.
    expect(waitingLine({ ...base, stepsSoFar: 6, saidSomething: true })).toBeNull();
  });

  it('says nothing while tokens are arriving', () => {
    // The answer typing itself out is the least ambiguous possible evidence
    // that something is happening; a line claiming a wait beside it is false.
    expect(waitingLine({ ...base, stepsSoFar: 2, streaming: true })).toBeNull();
  });

  it('says nothing while a human decision is holding the turn', () => {
    // Nothing is being waited *for* here except the reader.
    expect(waitingLine({ ...base, stepsSoFar: 2, awaitingApproval: true })).toBeNull();
  });

  it('says nothing once the turn has stopped running', () => {
    expect(waitingLine({ ...base, running: false })).toBeNull();
    expect(waitingLine({ ...base, running: false, stepsSoFar: 4 })).toBeNull();
  });

  it('never claims a step is doing something it has not said it is doing', () => {
    // The whole licence for this line is that it describes the *wait*. A
    // sentence naming work would be an invention: nothing on the wire says
    // what the next step is until that step narrates itself.
    for (const text of [WAITING_TO_START, WAITING_FOR_THE_NEXT_STEP]) {
      expect(text.toLowerCase()).toContain('waiting');
    }
  });
});
