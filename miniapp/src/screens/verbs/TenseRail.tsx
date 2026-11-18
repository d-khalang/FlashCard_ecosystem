import { useEffect, useRef, type KeyboardEvent, type PointerEvent } from 'react';
import { useI18n } from '../../i18n';
import { moodKey, tenseKey } from '../../verbs/labels';
import type { Mood, Tense } from '../../verbs/types';

interface TenseRailProps {
  tenses: readonly Pick<Tense, 'id' | 'mood'>[];
  current: number;
  /** Tenses beyond the user's level: drawn hollow. */
  secondary: ReadonlySet<string>;
  /** `instant`: while scrubbing, jump without animation. */
  onSelect: (index: number, instant: boolean) => void;
}

/**
 * Dots on a line, grouped by mood. The current dot stretches into a pill with the tense name.
 * Tap a dot to jump, drag along the rail to scrub, or use the arrow keys (one tab stop, roving focus).
 */
export function TenseRail({ tenses, current, secondary, onSelect }: TenseRailProps) {
  const { t } = useI18n();
  const dots = useRef<Array<HTMLButtonElement | null>>([]);
  /** Dot centers when the drag started: stable while the pill moves under the finger. */
  const drag = useRef<number[] | null>(null);
  const focusInside = useRef(false);

  // Keyboard: keep focus on the current dot as it moves.
  useEffect(() => {
    if (focusInside.current) dots.current[current]?.focus();
  }, [current]);

  const nearest = (x: number, centers: number[]) => {
    let best = 0;
    centers.forEach((c, i) => {
      if (Math.abs(c - x) < Math.abs(centers[best]! - x)) best = i;
    });
    return best;
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    drag.current = dots.current.map((d) => {
      const r = d?.getBoundingClientRect();
      return r ? r.left + r.width / 2 : Number.NaN;
    });
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const i = nearest(e.clientX, drag.current);
    if (i !== current) onSelect(i, false);
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const i = nearest(e.clientX, drag.current);
    if (i !== current) onSelect(i, true);
  };

  const endDrag = () => {
    drag.current = null;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const last = tenses.length - 1;
    const next: Record<string, number> = {
      ArrowRight: Math.min(current + 1, last),
      ArrowDown: Math.min(current + 1, last),
      ArrowLeft: Math.max(current - 1, 0),
      ArrowUp: Math.max(current - 1, 0),
      Home: 0,
      End: last,
    };
    const i = next[e.key];
    if (i === undefined) return;
    e.preventDefault();
    if (i !== current) onSelect(i, false);
  };

  // Group consecutive tenses by mood, keeping each tense's index.
  const groups: Array<{ mood: Mood; items: Array<{ id: Tense['id']; index: number }> }> = [];
  tenses.forEach((tense, index) => {
    const last = groups[groups.length - 1];
    if (last && last.mood === tense.mood) last.items.push({ id: tense.id, index });
    else groups.push({ mood: tense.mood, items: [{ id: tense.id, index }] });
  });

  return (
    <div
      className="rail"
      role="toolbar"
      aria-label={t('verbs.rail')}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      onFocus={() => (focusInside.current = true)}
      onBlur={() => (focusInside.current = false)}
    >
      {groups.map((g) => (
        <div key={g.mood} className="rail-group">
          {g.items.map(({ id, index }) => {
            const isCurrent = index === current;
            const cls = ['rail-dot', isCurrent ? 'is-current' : '', secondary.has(id) ? 'is-secondary' : ''].filter(Boolean).join(' ');
            return (
              <button
                key={id}
                ref={(el) => {
                  dots.current[index] = el;
                }}
                type="button"
                className={cls}
                tabIndex={isCurrent ? 0 : -1}
                aria-current={isCurrent ? 'true' : undefined}
                aria-label={t('verbs.railDot', { mood: t(moodKey(g.mood)), tense: t(tenseKey(id)), n: index + 1, total: tenses.length })}
                // Pointer taps are handled on pointerdown; this handles Enter and Space only (detail 0).
                onClick={(e) => e.detail === 0 && onSelect(index, false)}
              >
                <span className="rail-mark" aria-hidden="true">
                  <span className="rail-name">{isCurrent ? t(tenseKey(id)) : ''}</span>
                </span>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
