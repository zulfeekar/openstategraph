import { forwardRef, type ReactNode, type SelectHTMLAttributes } from 'react';
import clsx from 'clsx';
import { ChevronDown } from 'lucide-react';
import { Icon } from './Icon';
import { useFieldControl, type ControlSize } from './Field';
import './Select.css';

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
  /** Groups options under an `<optgroup>` heading. */
  group?: string;
  disabled?: boolean;
}

interface SelectProps<T extends string> extends Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  'children' | 'value' | 'onChange' | 'size'
> {
  options: readonly SelectOption<T>[];
  value: T;
  onValueChange: (value: T) => void;
  /** Glyph shown inside the control, left of the value. */
  leading?: ReactNode;
  /** Matches the shared control scale, so this can line up with a button. */
  size?: ControlSize;
  invalid?: boolean;
}

export const Select = forwardRef(function Select<T extends string>(
  {
    options,
    value,
    onValueChange,
    leading,
    size = 'md',
    invalid,
    className,
    disabled,
    ...rest
  }: SelectProps<T>,
  ref: React.Ref<HTMLSelectElement>,
) {
  const control = useFieldControl({
    describedBy: rest['aria-describedby'],
    invalid,
  });
  // Preserve declaration order while collecting groups, so the rendered
  // popup matches the order the caller registered options in.
  const groups: { name: string | undefined; options: readonly SelectOption<T>[] }[] = [];
  for (const option of options) {
    const last = groups[groups.length - 1];
    if (last && last.name === option.group) {
      (last.options as SelectOption<T>[]).push(option);
    } else {
      groups.push({ name: option.group, options: [option] });
    }
  }

  return (
    <div
      className={clsx('select', size !== 'md' && `select--${size}`, className)}
      data-disabled={disabled || undefined}
      data-invalid={control.invalid || undefined}
    >
      {leading ? <span className="select__leading">{leading}</span> : null}
      <select
        ref={ref}
        className="select__control"
        value={value}
        disabled={disabled}
        onChange={(event) => onValueChange(event.target.value as T)}
        {...rest}
        aria-describedby={control.describedBy}
        aria-invalid={control.invalid || undefined}
      >
        {groups.map((group, index) =>
          group.name ? (
            <optgroup key={group.name} label={group.name}>
              {group.options.map((option) => (
                <option key={option.value} value={option.value} disabled={option.disabled}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          ) : (
            group.options.map((option) => (
              <option
                key={`${index}-${option.value}`}
                value={option.value}
                disabled={option.disabled}
              >
                {option.label}
              </option>
            ))
          ),
        )}
      </select>
      <span className="select__chevron">
        <Icon glyph={ChevronDown} size="sm" />
      </span>
    </div>
  );
}) as <T extends string>(
  props: SelectProps<T> & { ref?: React.Ref<HTMLSelectElement> },
) => ReactNode;
