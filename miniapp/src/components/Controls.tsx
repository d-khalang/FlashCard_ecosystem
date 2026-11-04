import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronRight, Minus, Plus } from 'lucide-react';
import { Flag } from './Flag';
import { Sheet } from './Sheet';
import { useI18n } from '../i18n';

interface Option<V extends string> {
  value: V;
  label: string;
  help?: string;
}

interface SegmentedProps<V extends string> {
  label: string;
  value: V;
  options: readonly Option<V>[];
  onChange: (v: V) => void;
}

/** Single-choice group of pill buttons. */
export function Segmented<V extends string>({ label, value, options, onChange }: SegmentedProps<V>) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          className={o.value === value ? 'seg is-on' : 'seg'}
          onClick={() => o.value !== value && onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

interface LanguageOption {
  code: string;
  name: string;
  country: string | null;
}

interface LanguagePickerProps {
  label: string;
  value: string | null;
  options: readonly LanguageOption[];
  onChange: (code: string | null) => void;
  /** When set, a "None" choice is offered. */
  noneLabel?: string;
}

/** One row showing the current language; tapping it opens the full list in a sheet. */
export function LanguagePicker({ label, value, options, onChange, noneLabel }: LanguagePickerProps) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.code === value);
  const pick = (code: string | null) => {
    setOpen(false);
    if (code !== value) onChange(code);
  };
  return (
    <>
      <button type="button" className="picker-row" aria-haspopup="dialog" aria-label={`${label}: ${current?.name ?? noneLabel ?? ''}`} onClick={() => setOpen(true)}>
        {current ? <Flag country={current.country} name={current.name} /> : null}
        <span className="picker-value">{current?.name ?? noneLabel}</span>
        <ChevronRight size={20} strokeWidth={2.8} aria-hidden="true" />
      </button>
      {open ? (
        <Sheet title={label} onClose={() => setOpen(false)}>
          <div className="lang-list" role="radiogroup" aria-label={label}>
            {noneLabel ? (
              <button type="button" role="radio" aria-checked={value === null} className={value === null ? 'lang-chip is-on' : 'lang-chip'} onClick={() => pick(null)}>
                {noneLabel}
              </button>
            ) : null}
            {options.map((o) => (
              <button
                key={o.code}
                type="button"
                role="radio"
                aria-checked={o.code === value}
                className={o.code === value ? 'lang-chip is-on' : 'lang-chip'}
                onClick={() => pick(o.code)}
              >
                <Flag country={o.country} name={o.name} />
                <span>{o.name}</span>
              </button>
            ))}
          </div>
        </Sheet>
      ) : null}
    </>
  );
}

interface SwitchProps {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}

export function Switch({ label, description, checked, onChange }: SwitchProps) {
  return (
    <button type="button" role="switch" aria-checked={checked} className="switch-row" onClick={() => onChange(!checked)}>
      <span className="switch-text">
        <span className="switch-label">{label}</span>
        <span className="switch-desc">{description}</span>
      </span>
      <span className={checked ? 'switch-track is-on' : 'switch-track'} aria-hidden="true">
        <span className="switch-thumb" />
      </span>
    </button>
  );
}

interface StepperProps {
  label: string;
  value: number;
  min: number;
  max: number;
  format: (v: number) => string;
  onCommit: (v: number) => void;
}

/** Step size grows with the value: fine control for short intervals, coarse for long ones. */
export function stepFor(value: number, direction: 1 | -1): number {
  const edge = direction === 1 ? value : value - 1;
  if (edge < 120) return 15;
  if (edge < 720) return 30;
  return 60;
}

export function nextInterval(value: number, direction: 1 | -1, min: number, max: number): number {
  const next = value + direction * stepFor(value, direction);
  return Math.min(max, Math.max(min, next));
}

/** Minus / value / plus. Taps update at once; the change is committed after a short pause. */
export function Stepper({ label, value, min, max, format, onCommit }: StepperProps) {
  const { t } = useI18n();
  const [shown, setShown] = useState(value);
  const timer = useRef<number | undefined>(undefined);
  const dirty = useRef(false);

  useEffect(() => {
    if (!dirty.current) setShown(value);
  }, [value]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const bump = (dir: 1 | -1) => {
    const next = nextInterval(shown, dir, min, max);
    if (next === shown) return;
    dirty.current = true;
    setShown(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      dirty.current = false;
      onCommit(next);
    }, 600);
  };

  return (
    <div className="stepper" role="group" aria-label={label}>
      <button type="button" className="step-btn" onClick={() => bump(-1)} disabled={shown <= min} aria-label={t('settings.intervalLess')}>
        <Minus size={22} strokeWidth={3} aria-hidden="true" />
      </button>
      <output className="step-value" aria-live="polite">
        {format(shown)}
      </output>
      <button type="button" className="step-btn" onClick={() => bump(1)} disabled={shown >= max} aria-label={t('settings.intervalMore')}>
        <Plus size={22} strokeWidth={3} aria-hidden="true" />
      </button>
    </div>
  );
}

interface FieldProps {
  label: string;
  hint?: string;
  children: ReactNode;
}

export function Field({ label, hint, children }: FieldProps) {
  return (
    <section className="field">
      <h2 className="field-label">{label}</h2>
      {hint ? <p className="field-hint">{hint}</p> : null}
      {children}
    </section>
  );
}
