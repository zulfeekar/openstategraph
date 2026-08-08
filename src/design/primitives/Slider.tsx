import { forwardRef, type InputHTMLAttributes } from 'react';
import clsx from 'clsx';
import './Slider.css';

interface SliderProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'value' | 'onChange' | 'type'
> {
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onValueChange: (value: number) => void;
  /** Fired once when the drag ends — the point at which we commit a command. */
  onValueCommit?: (value: number) => void;
}

export const Slider = forwardRef<HTMLInputElement, SliderProps>(function Slider(
  {
    value,
    min = 0,
    max = 100,
    step = 1,
    onValueChange,
    onValueCommit,
    className,
    disabled,
    ...rest
  },
  ref,
) {
  const span = max - min;
  const fill = span > 0 ? ((value - min) / span) * 100 : 0;

  const commit = (next: number) => onValueCommit?.(next);

  return (
    <div
      className={clsx('slider', className)}
      style={{ ['--slider-fill' as string]: `${Math.min(100, Math.max(0, fill))}%` }}
      data-disabled={disabled || undefined}
    >
      <input
        ref={ref}
        type="range"
        className="slider__control"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => onValueChange(event.target.valueAsNumber)}
        // Commit on the interaction boundaries so a drag produces one
        // undo entry rather than one per pixel.
        onPointerUp={(event) => commit(event.currentTarget.valueAsNumber)}
        onKeyUp={(event) => commit(event.currentTarget.valueAsNumber)}
        onBlur={(event) => commit(event.currentTarget.valueAsNumber)}
        {...rest}
      />
    </div>
  );
});
