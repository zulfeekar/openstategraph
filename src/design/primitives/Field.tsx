import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react';
import clsx from 'clsx';
import './Field.css';

/* ------------------------------------------------------------------ *
 * Field — the label / control / hint shell.
 * ------------------------------------------------------------------ */

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
  const caption = label ? (
    <>
      <span className="field__label">
        <span>{label}</span>
        {labelValue != null ? <span className="field__label-value">{labelValue}</span> : null}
      </span>
    </>
  ) : null;

  const detail = error ? (
    <span className="field__error">{error}</span>
  ) : hint ? (
    <span className="field__hint">{hint}</span>
  ) : null;

  // With an explicit `htmlFor`, the label points at a specific control.
  // Without one, the field renders *as* a label and wraps its control, which
  // associates them implicitly — so a caller that forgets to thread an id
  // still produces a properly named control rather than an anonymous one.
  // (The app's own accessibility audit is what surfaced that gap.)
  if (label && !htmlFor) {
    return (
      <label className={clsx('field', className)}>
        {caption}
        {children}
        {detail}
      </label>
    );
  }

  return (
    <div className={clsx('field', className)}>
      {label ? (
        <label className="field__label" htmlFor={htmlFor}>
          <span>{label}</span>
          {labelValue != null ? <span className="field__label-value">{labelValue}</span> : null}
        </label>
      ) : null}
      {children}
      {detail}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * TextInput
 * ------------------------------------------------------------------ */

interface TextInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size' | 'prefix'> {
  prefix?: ReactNode;
  suffix?: ReactNode;
  invalid?: boolean;
  mono?: boolean;
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { prefix, suffix, invalid, mono, className, disabled, ...rest },
  ref,
) {
  return (
    <div
      className={clsx('input', mono && 'input--mono', className)}
      data-invalid={invalid || undefined}
      data-disabled={disabled || undefined}
    >
      {prefix ? <span className="input__prefix">{prefix}</span> : null}
      <input ref={ref} className="input__control" disabled={disabled} {...rest} />
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
}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { invalid, mono, minRows = 2, className, disabled, value, onChange, ...rest },
  ref,
) {
  const innerRef = useRef<HTMLTextAreaElement | null>(null);

  const resize = useCallback(() => {
    const el = innerRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, []);

  // Re-measure on mount and whenever the controlled value changes, so a
  // programmatic edit (undo, import) grows the box just like typing does.
  useLayoutEffect(resize, [resize, value]);

  useEffect(() => {
    const el = innerRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    // A node resize changes the wrap width, which changes the height.
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    return () => observer.disconnect();
  }, [resize]);

  return (
    <div
      className={clsx('input', 'input--textarea', mono && 'input--mono', className)}
      data-invalid={invalid || undefined}
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
