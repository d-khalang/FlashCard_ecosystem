import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Info } from 'lucide-react';
import { useI18n } from '../../i18n';
import { pushBackHandler } from '../../telegram';
import { tenseIndex } from '../../verbs/labels';
import type { LookupFound, Person, TenseId } from '../../verbs/types';
import { TenseCard } from './TenseCard';
import { TenseRail } from './TenseRail';

interface VerbDeckProps {
  result: LookupFound;
  /** Tense to show first; default: the first matched slot's tense, else indicativo-presente. */
  tenseId?: TenseId;
  onTenseChange: (id: TenseId) => void;
  onBack: () => void;
  onDrill: (id: TenseId) => void;
  onLookup: (infinitive: string) => void;
}

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return reduced;
}

/** Swipeable tense cards (CSS scroll-snap), prev/next buttons for desktop and screen readers, and the tense rail. */
export function VerbDeck({ result, tenseId, onTenseChange, onBack, onDrill, onLookup }: VerbDeckProps) {
  const { t } = useI18n();
  const { verb, match } = result;
  const reduced = usePrefersReducedMotion();
  const tenses = useMemo(() => [...verb.tenses].sort((a, b) => tenseIndex(a.id) - tenseIndex(b.id)), [verb]);
  const secondary = useMemo(() => {
    const level = new Set<string>(result.level_tenses);
    return new Set(tenses.filter((x) => !level.has(x.id)).map((x) => x.id));
  }, [tenses, result.level_tenses]);
  const matchedBy = useMemo(() => {
    const m = new Map<TenseId, Set<Person>>();
    for (const s of match.slots) m.set(s.tense_id, (m.get(s.tense_id) ?? new Set()).add(s.person));
    return m;
  }, [match]);

  const startId = tenseId ?? match.slots[0]?.tense_id ?? 'indicativo-presente';
  const [current, setCurrent] = useState(() => Math.max(0, tenses.findIndex((x) => x.id === startId)));
  const track = useRef<HTMLDivElement>(null);
  /** While a programmatic scroll runs, scroll events must not move the rail through the tenses in between. */
  const target = useRef<number | null>(null);
  const targetTimer = useRef<number | undefined>(undefined);

  useEffect(() => pushBackHandler(onBack), [onBack]);

  const step = () => {
    const el = track.current;
    const first = el?.firstElementChild as HTMLElement | null;
    if (!el || !first) return 0;
    const gap = Number.parseFloat(getComputedStyle(el).columnGap) || 0;
    return first.offsetWidth + gap;
  };

  const scrollToIndex = useCallback(
    (i: number, behavior: ScrollBehavior) => {
      const el = track.current;
      if (!el) return;
      const left = i * step();
      if (typeof el.scrollTo === 'function') el.scrollTo({ left, behavior });
      else el.scrollLeft = left;
    },
    [],
  );

  // Open on the start tense without animation.
  useLayoutEffect(() => {
    scrollToIndex(current, 'auto');
    // Only on mount: later moves come from the user.
  }, []);

  useEffect(() => {
    const id = tenses[current]?.id;
    if (id) onTenseChange(id);
  }, [current, tenses, onTenseChange]);

  const go = (i: number, instant = false) => {
    const next = Math.max(0, Math.min(tenses.length - 1, i));
    target.current = next;
    window.clearTimeout(targetTimer.current);
    targetTimer.current = window.setTimeout(() => (target.current = null), 700);
    setCurrent(next);
    scrollToIndex(next, instant || reduced ? 'auto' : 'smooth');
  };

  const onScroll = () => {
    const el = track.current;
    const w = step();
    if (!el || !w) return;
    const i = Math.round(el.scrollLeft / w);
    if (target.current !== null) {
      if (i === target.current) target.current = null;
      return;
    }
    if (i !== current && i >= 0 && i < tenses.length) setCurrent(i);
  };

  const cur = tenses[current];
  const aux = verb.auxiliaries.filter((a) => a.primary).map((a) => a.verb);
  const subtitle = [result.meaning, ...aux, verb.principal_forms.gerund, verb.principal_forms.past_participle].filter(Boolean).join(' · ');

  return (
    <div className="verb-deck">
      <header className="deck-head">
        <button type="button" className="icon-btn icon-btn-boxed" aria-label={t('verbs.back')} onClick={onBack}>
          <ChevronLeft size={22} strokeWidth={2.6} aria-hidden="true" />
        </button>
        <div className="deck-titles">
          <h1 className="deck-verb" lang="it">
            {verb.infinitive}
          </h1>
          <p className="deck-sub" lang="it">
            {subtitle}
          </p>
        </div>
      </header>

      {match.kind === 'fuzzy' ? (
        <p className="deck-notice" role="status">
          <Info size={16} strokeWidth={2.6} aria-hidden="true" />
          {t('verbs.fuzzy', { verb: verb.infinitive, query: match.query })}
        </p>
      ) : null}
      {match.candidates.length > 0 ? (
        <p className="deck-also">
          <span>{t('verbs.alsoTry')}</span>
          {match.candidates.map((c) => (
            <button key={c} type="button" className="link-btn" lang="it" onClick={() => onLookup(c)}>
              {c}
            </button>
          ))}
        </p>
      ) : null}

      <div className="deck-track" ref={track} onScroll={onScroll} aria-label={verb.infinitive} aria-roledescription="carousel">
        {tenses.map((tense, i) => (
          <div key={tense.id} className="deck-slide" inert={i !== current}>
            <TenseCard
              tense={tense}
              position={i + 1}
              total={tenses.length}
              secondary={secondary.has(tense.id)}
              matched={matchedBy.get(tense.id) ?? new Set()}
            />
          </div>
        ))}
      </div>

      <div className="deck-rail">
        <TenseRail tenses={tenses} current={current} secondary={secondary} onSelect={go} />
      </div>

      <div className="deck-actions">
        <button type="button" className="btn icon-btn-lg" aria-label={t('verbs.prev')} disabled={current === 0} onClick={() => go(current - 1)}>
          <ChevronLeft size={24} strokeWidth={2.6} aria-hidden="true" />
        </button>
        <button type="button" className="btn btn-primary grow" disabled={!cur} onClick={() => cur && onDrill(cur.id)}>
          {t('verbs.drill')}
        </button>
        <button
          type="button"
          className="btn icon-btn-lg"
          aria-label={t('verbs.next')}
          disabled={current === tenses.length - 1}
          onClick={() => go(current + 1)}
        >
          <ChevronRight size={24} strokeWidth={2.6} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
