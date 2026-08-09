/**
 * Explicit success/failure for operations whose failure is an expected
 * outcome rather than a bug: connection validation, deserialization,
 * provider calls.
 *
 * Exceptions are reserved for programming errors. Anything a user can
 * trigger by drawing an invalid link or pasting a bad file returns a
 * Result, so the call site is forced to handle it.
 */
export type Result<T, E = string> =
  { readonly ok: true; readonly value: T } | { readonly ok: false; readonly error: E };

export const Ok = <T>(value: T): Result<T, never> => ({ ok: true, value });
export const Err = <E>(error: E): Result<never, E> => ({ ok: false, error });

/** Runs a throwing function and normalises the throw into an `Err`. */
export function attempt<T>(fn: () => T): Result<T, Error> {
  try {
    return Ok(fn());
  } catch (error) {
    return Err(error instanceof Error ? error : new Error(String(error)));
  }
}
