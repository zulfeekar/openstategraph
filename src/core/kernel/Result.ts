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

export function isOk<T, E>(result: Result<T, E>): result is { ok: true; value: T } {
  return result.ok;
}

export function unwrapOr<T, E>(result: Result<T, E>, fallback: T): T {
  return result.ok ? result.value : fallback;
}

export function mapResult<T, U, E>(result: Result<T, E>, fn: (value: T) => U): Result<U, E> {
  return result.ok ? Ok(fn(result.value)) : result;
}

/** Runs a throwing function and normalises the throw into an `Err`. */
export function attempt<T>(fn: () => T): Result<T, Error> {
  try {
    return Ok(fn());
  } catch (error) {
    return Err(error instanceof Error ? error : new Error(String(error)));
  }
}

export async function attemptAsync<T>(fn: () => Promise<T>): Promise<Result<T, Error>> {
  try {
    return Ok(await fn());
  } catch (error) {
    return Err(error instanceof Error ? error : new Error(String(error)));
  }
}
