import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  type CSSProperties,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react';
import clsx from 'clsx';
import './Field.css';

/** The three sizes every control in this system shares. */
export type ControlSize = 'sm' | 'md' | 'lg';

/* ------------------------------------------------------------------ *
 * Field — the label / control / hint shell.
 * ------------------------------------------------------------------ */

/**
 * What a `Field` tells the control inside it.
 *
 * The hint and the error are rendered by the shell, so only the shell
 * knows their ids — and without them the control has nothing to point
 * `aria-describedby` at, which is how an error message ends up visible
 * on screen and absent from the accessibility tree. Publishing them here
 * lets `TextInput`, `TextArea` and `Select` wire themselves up, while an
 * explicit prop on the call site still wins.
 */
interface FieldContextValue {
  describedBy: string | undefined;
  invalid: boolean;
}

const FieldContext = createContext<FieldContextValue | null>(null);

interface FieldProps {
  label?: string;
  /** Right-aligned readout appended to the label, e.g. "· 500". */
  labelValue?: ReactNode;
  hint?: string;
  error?: string;
  /** `id` to associate the label with; usually from `useId()`. */
  htmlFor?: string;
  className?: string;
  children: ReactNode;
}

export function Field({
  label,
  labelValue,
  hint,
  error,
  htmlFor,
  className,
  children,
}: FieldProps) {
  const detailId = useId();

  const caption = label ? (
    <>
      <span className="field__label" data-error={error ? 'true' : undefined}>
        <span>{label}</span>
        {labelValue != null ? <span className="field__label-value">{labelValue}</span> : null}
      </span>
    </>
  ) : null;

  // Error replaces hint rather than stacking below it: node bodies are
  // height-constrained and sit on a canvas, so growing a field by a line
  // would shove every node beneath it down the screen.
  const detail = error ? (
    <span className="field__error" id={detailId}>
      {error}
    </span>
  ) : hint ? (
    <span className="field__hint" id={detailId}>
      {hint}
    </span>
  ) : null;

  const hasDetail = Boolean(error ?? hint);
  const context = useMemo<FieldContextValue>(
    () => ({
      describedBy: hasDetail ? detailId : undefined,
      invalid: Boolean(error),
    }),
    [hasDetail, detailId, error],
  );

  // With an explicit `htmlFor`, the label points at a specific control.
  // Without one, the field renders *as* a label and wraps its control, which
  // associates them implicitly — so a caller that forgets to thread an id
  // still produces a properly named control rather than an anonymous one.
  // (The app's own accessibility audit is what surfaced that gap.)
  if (label && !htmlFor) {
    return (
      <label className={clsx('field', className)}>
        {caption}
        <FieldContext.Provider value={context}>{children}</FieldContext.Provider>
        {detail}
      </label>
    );
  }

  return (
    <div className={clsx('field', className)}>
      {label ? (
        <label className="field__label" htmlFor={htmlFor} data-error={error ? 'true' : undefined}>
          <span>{label}</span>
          {labelValue != null ? <span className="field__label-value">{labelValue}</span> : null}
        </label>
      ) : null}
      <FieldContext.Provider value={context}>{children}</FieldContext.Provider>
      {detail}
    </div>
  );
}

/**
 * The `aria-describedby` / `aria-invalid` a control should carry, given
 * what its surrounding `Field` is showing and what the caller asked for.
 * An explicit prop always wins; the field only fills a gap.
 */
export function useFieldControl(explicit: {
  describedBy?: string | undefined;
  invalid?: boolean | undefined;
}): { describedBy: string | undefined; invalid: boolean | undefined } {
  const field = useContext(FieldContext);
  return {
    describedBy: explicit.describedBy ?? field?.describedBy,
    invalid: explicit.invalid ?? field?.invalid,
  };
}

/* ------------------------------------------------------------------ *
 * TextInput
 * ------------------------------------------------------------------ */

interface TextInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size' | 'prefix'> {
  prefix?: ReactNode;
  suffix?: ReactNode;
  invalid?: boolean;
  mono?: boolean;
  /** Matches the shared control scale, so this can line up with a button. */
  size?: ControlSize;
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { prefix, suffix, invalid, mono, size = 'md', className, disabled, ...rest },
  ref,
) {
  const control = useFieldControl({
    describedBy: rest['aria-describedby'],
    invalid,
  });

  return (
    <div
      className={clsx('input', size !== 'md' && `input--${size}`, mono && 'input--mono', className)}
      data-invalid={control.invalid || undefined}
      data-disabled={disabled || undefined}
    >
      {prefix ? <span className="input__prefix">{prefix}</span> : null}
      <input
        ref={ref}
        className="input__control"
        disabled={disabled}
        {...rest}
        aria-describedby={control.describedBy}
        aria-invalid={control.invalid || undefined}
      />
      {suffix ? <span className="input__suffix">{suffix}</span> : null}
    </div>
  );
});

/* ------------------------------------------------------------------ *
 * TextArea — height tracks content, because a node card that scrolls
 * internally is much harder to read than one that grows.
 * ------------------------------------------------------------------ */

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
  mono?: boolean;
  /** Rows to reserve before content forces a grow. */
  minRows?: number;
  /**
   * Rows the box may grow to before it scrolls instead (ticket 26).
   *
   * Published to CSS as `--textarea-max-rows` rather than measured here: the
   * stylesheet already owns the line height, and `calc(n * 1lh)` is the same
   * arithmetic with none of the resynchronising a JS copy would need on every
   * font or density change.
   */
  maxRows?: number;
}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { invalid, mono, minRows = 2, maxRows = 12, className, disabled, value, onChange, ...rest },
  ref,
) {
  const control = useFieldControl({
    describedBy: rest['aria-describedby'],
    invalid,
  });
  const innerRef = useRef<HTMLTextAreaElement | null>(null);
  /**
   * A height the developer dragged to, which from then on wins.
   *
   * Auto-growth is a default, not a policy: someone reading a long prompt may
   * want the box taller than its ceiling, and a control that snapped back to
   * the computed height on the next keystroke would be a resize handle that
   * does not resize. Once they have said what height they want, this stops
   * measuring — the same rule the canvas follows when a node is dragged.
   */
  const manual = useRef(false);
  /** The last height *we* applied, so a height we did not apply is theirs. */
  const applied = useRef<number | null>(null);

  const resize = useCallback(() => {
    const el = innerRef.current;
    if (!el || manual.current) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
    // Read back rather than trusting the write: `max-height` caps it, and the
    // capped value is what a later observation has to be compared against.
    applied.current = el.offsetHeight;
  }, []);

  // Re-measure on mount and whenever the controlled value changes, so a
  // programmatic edit (undo, import) grows the box just like typing does.
  useLayoutEffect(resize, [resize, value]);

  useEffect(() => {
    const el = innerRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    // A node resize changes the wrap width, which changes the height — and a
    // drag of the grabber changes the height directly. Both arrive here, and
    // the difference between them is whether the height is the one we left.
    const observer = new ResizeObserver(() => {
      const last = applied.current;
      if (last !== null && Math.abs(el.offsetHeight - last) > 1) {
        manual.current = true;
        return;
      }
      resize();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [resize]);

  return (
    <div
      className={clsx('input', 'input--textarea', mono && 'input--mono', className)}
      style={{ '--textarea-max-rows': maxRows } as CSSProperties}
      data-invalid={control.invalid || undefined}
      data-disabled={disabled || undefined}
    >
      <textarea
        ref={(node) => {
          innerRef.current = node;
          if (typeof ref === 'function') ref(node);
          else if (ref) ref.current = node;
        }}
        className="input__control"
        rows={minRows}
        disabled={disabled}
        value={value}
        onChange={(event) => {
          onChange?.(event);
          resize();
        }}
        {...rest}
        aria-describedby={control.describedBy}
        aria-invalid={control.invalid || undefined}
      />
    </div>
  );
});

/* ------------------------------------------------------------------ *
 * DisplayRow — input-shaped, but the value is a token plus an action.
 * ------------------------------------------------------------------ */

interface DisplayRowProps {
  value: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}

export function DisplayRow({ value, action, icon, className }: DisplayRowProps) {
  return (
    <div className={clsx('input', 'input--display', className)}>
      {icon ? <span className="input__prefix">{icon}</span> : null}
      <span className="input__control">{value}</span>
      {action}
    </div>
  );
}

/** Convenience: a stable id for label/control pairing. */
export function useFieldId(prefix: string): string {
  const id = useId();
  return `${prefix}${id}`;
}
