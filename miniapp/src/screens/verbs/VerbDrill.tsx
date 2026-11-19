import { useEffect, useLayoutEffect, useReducer, useRef, useState, type FormEvent } from 'react';
import { Loader2, X } from 'lucide-react';
import { asApiError, type ApiError } from '../../api/errors';
import { useApp } from '../../app/context';
import { ErrorState } from '../../components/ErrorState';
import { useI18n } from '../../i18n';
import { haptic, pushBackHandler } from '../../telegram';
import { drillReducer, practiceBody, score, startDrill, type Answered, type DrillState } from '../../verbs/drillSession';
import { counts } from '../../verbs/grade';
import { moodKey, moodOf, personKey, tenseKey } from '../../verbs/labels';
import type { Drill, DrillItem, TenseId } from '../../verbs/types';

const ACCENTS = ['à', 'è', 'é', 'ì', 'ò', 'ù'] as const;
/** Below this visible height (keyboard open on a phone) the drill tightens its layout. */
const SHORT_PX = 520;

/** The visible part of the window: shrinks when the on-screen keyboard opens. */
function useVisualViewport(): { height: number; top: number } | null {
  const [box, setBox] = useState<{ height: number; top: number } | null>(null);
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const update = () => setBox({ height: Math.round(vv.height), top: Math.round(vv.offsetTop) });
    update();
    vv.addEventListener('resize', update);
    vv.addEventListener('scroll', update);
    return () => {
      vv.removeEventListener('resize', update);
      vv.removeEventListener('scroll', update);
    };
  }, []);
  return box;
}

interface VerbDrillProps {
  infinitive: string;
  tenseId: TenseId;
  onExit: () => void;
}

export function VerbDrill({ infinitive, tenseId, onExit }: VerbDrillProps) {
  const { api } = useApp();
  const { t } = useI18n();
  const [drill, setDrill] = useState<Drill | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const vv = useVisualViewport();

  useEffect(() => pushBackHandler(onExit), [onExit]);

  const load = () => {
    setError(null);
    setDrill(null);
    api.verbs.drill(infinitive, tenseId).then(setDrill, (e: unknown) => setError(asApiError(e)));
  };
  useEffect(load, [api, infinitive, tenseId]);

  const style = vv ? { height: `${vv.height}px`, top: `${vv.top}px` } : undefined;
  return (
    <div className={vv && vv.height < SHORT_PX ? 'verb-drill is-short' : 'verb-drill'} style={style} role="dialog" aria-modal="true" aria-label={`${infinitive} · ${t(moodKey(moodOf(tenseId)))} ${t(tenseKey(tenseId))}`}>
      {error ? (
        <>
          <DrillTop onExit={onExit} />
          <ErrorState error={error} onRetry={load} />
        </>
      ) : !drill ? (
        <>
          <DrillTop onExit={onExit} />
          <p className="verb-loading screen-center" role="status">
            <Loader2 size={22} strokeWidth={2.6} className="spin" aria-hidden="true" />
            {t('verbs.drill.loading')}
          </p>
        </>
      ) : drill.items.length === 0 ? (
        <>
          <DrillTop onExit={onExit} />
          <p className="screen-center">{t('verbs.drill.empty')}</p>
        </>
      ) : (
        <DrillRun drill={drill} onExit={onExit} />
      )}
    </div>
  );
}

function DrillTop({ onExit, progress }: { onExit: () => void; progress?: { done: number; total: number; retry: boolean } }) {
  const { t } = useI18n();
  return (
    <header className="drill-top">
      <button type="button" className="icon-btn icon-btn-boxed" aria-label={t('verbs.drill.stop')} onClick={onExit}>
        <X size={20} strokeWidth={2.6} aria-hidden="true" />
      </button>
      {progress ? (
        <>
          <div
            className="drill-progress"
            role="progressbar"
            aria-label={t('verbs.drill.progress')}
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.done}
          >
            <span style={{ width: `${(progress.done / progress.total) * 100}%` }} />
          </div>
          <span className="drill-count">
            {progress.retry ? `${t('verbs.drill.retryRound')} · ` : ''}
            {Math.min(progress.done + 1, progress.total)} / {progress.total}
          </span>
        </>
      ) : null}
    </header>
  );
}

function DrillRun({ drill, onExit }: { drill: Drill; onExit: () => void }) {
  const { api, toast } = useApp();
  const { t } = useI18n();
  const [state, dispatch] = useReducer(drillReducer, drill, startDrill);
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);
  const sent = useRef<DrillState | null>(null);

  const item = state.round[state.index];
  const answered = state.phase === 'feedback' ? state.answers[state.index] : undefined;
  const mood = moodOf(drill.tense_id);

  // Clear the box when the item changes, during render: an effect would also run after mount, late enough
  // (the drill mounts after a fetch) to wipe what was already typed.
  const [shownItem, setShownItem] = useState({ index: state.index, round: state.round });
  if (shownItem.index !== state.index || shownItem.round !== state.round) {
    setShownItem({ index: state.index, round: state.round });
    setInput('');
  }

  // Keep focus in the box (and the keyboard up) across check, show and next, so Enter always works.
  useEffect(() => {
    if (state.phase !== 'summary') inputRef.current?.focus({ preventScroll: true });
  }, [state.phase, state.index, state.round]);

  // Put the caret after an inserted accent.
  useLayoutEffect(() => {
    if (caret.current === null || !inputRef.current) return;
    inputRef.current.setSelectionRange(caret.current, caret.current);
    caret.current = null;
  }, [input]);

  // Feedback haptics.
  useEffect(() => {
    if (answered) haptic(counts(answered.verdict) ? 'success' : 'error');
  }, [answered]);

  // One practice record per finished full round.
  useEffect(() => {
    const body = practiceBody(state);
    if (!body || sent.current === state) return;
    sent.current = state;
    api.verbs.practice(body).catch(() => toast(t('verbs.drill.saveFailed'), 'error'));
  }, [state, api, toast, t]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    dispatch({ type: 'enter', input: inputRef.current?.value ?? input });
  };

  const insert = (ch: string) => {
    const el = inputRef.current;
    if (!el || state.phase !== 'answer') return;
    const start = el.selectionStart ?? input.length;
    const end = el.selectionEnd ?? input.length;
    caret.current = start + ch.length;
    setInput(input.slice(0, start) + ch + input.slice(end));
    el.focus();
  };

  if (state.phase === 'summary') {
    return <DrillSummary state={state} onExit={onExit} onRetry={() => dispatch({ type: 'retryWrong' })} onRestart={() => dispatch({ type: 'restart' })} />;
  }
  if (!item) return null;

  const last = state.index + 1 >= state.round.length;
  const inputClass = ['drill-input', answered ? (counts(answered.verdict) ? 'is-right' : 'is-wrong') : ''].filter(Boolean).join(' ');

  return (
    <form className="drill-body" onSubmit={onSubmit}>
      <DrillTop onExit={onExit} progress={{ done: state.index, total: state.round.length, retry: state.retry }} />

      <section className="drill-card">
        <span className="drill-tag" lang="it">
          {drill.infinitive} · {t(moodKey(mood))} {t(tenseKey(drill.tense_id))}
        </span>
        <p className="drill-prompt" lang="it">
          {t(personKey(mood, item.person))} <span className="drill-blank" aria-hidden="true" />
        </p>
      </section>

      <div className="field">
        <label className="field-label" htmlFor="drill-answer">
          {t('verbs.drill.answer')}
        </label>
        <input
          id="drill-answer"
          ref={inputRef}
          className={inputClass}
          type="text"
          lang="it"
          enterKeyHint={state.phase === 'answer' ? 'done' : 'next'}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          autoFocus
          readOnly={state.phase !== 'answer'}
          aria-invalid={answered && !counts(answered.verdict) ? true : undefined}
          aria-describedby={answered ? 'drill-feedback' : undefined}
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <div className="accent-keys" role="group" aria-label={t('verbs.drill.accents')}>
          {ACCENTS.map((ch) => (
            <button
              key={ch}
              type="button"
              className="accent-key"
              aria-label={t('verbs.drill.insert', { char: ch })}
              disabled={state.phase !== 'answer'}
              // Keep focus (and the keyboard) in the input.
              onPointerDown={(e) => e.preventDefault()}
              onClick={() => insert(ch)}
            >
              {ch}
            </button>
          ))}
        </div>
      </div>

      {answered ? <Feedback item={item} answered={answered} /> : null}

      <div className="drill-actions">
        {state.phase === 'answer' ? (
          <>
            <button type="submit" className="btn btn-primary" disabled={!input.trim()}>
              {t('verbs.drill.check')}
            </button>
            <button
              type="button"
              className="link-btn drill-show"
              onPointerDown={(e) => e.preventDefault()}
              onClick={() => dispatch({ type: 'show' })}
            >
              {t('verbs.drill.show')}
            </button>
          </>
        ) : (
          <button type="submit" className="btn btn-primary">
            {last ? t('verbs.drill.results') : t('verbs.drill.next')}
          </button>
        )}
      </div>
    </form>
  );
}

function Feedback({ item, answered }: { item: DrillItem; answered: Answered }) {
  const { t } = useI18n();
  const { verdict } = answered;
  const ok = counts(verdict);
  const title =
    verdict.result === 'right'
      ? t('verbs.drill.right', { answer: item.primary })
      : verdict.result === 'accent'
        ? t('verbs.drill.accent', { answer: item.primary })
        : answered.shown
          ? t('verbs.drill.shown', { answer: item.primary })
          : t('verbs.drill.wrong', { answer: item.primary });
  const note = verdict.result === 'right' && verdict.note ? t(`verbs.drill.note.${verdict.note}`) : null;
  const hint = !ok && item.hint ? (item.hint.kind === 'irregular_stem' ? t('verbs.drill.hint.stem', { stem: item.hint.stem }) : t('verbs.drill.hint.form')) : null;
  return (
    <div id="drill-feedback" className={ok ? 'drill-feedback is-right' : 'drill-feedback is-wrong'} role="status">
      <strong lang="it">{title}</strong>
      {note ? <span>{note}</span> : null}
      {hint ? <span lang="it">{hint}</span> : null}
    </div>
  );
}

function DrillSummary({ state, onExit, onRetry, onRestart }: { state: DrillState; onExit: () => void; onRetry: () => void; onRestart: () => void }) {
  const { t } = useI18n();
  const s = score(state);
  const mood = moodOf(state.drill.tense_id);
  const missedItems = state.round.filter((it) => s.missed.includes(it.person));
  return (
    <div className="drill-body">
      <DrillTop onExit={onExit} />
      <section className="drill-card drill-summary" role="status">
        <span className="drill-tag" lang="it">
          {state.drill.infinitive} · {t(moodKey(mood))} {t(tenseKey(state.drill.tense_id))}
        </span>
        <h2 className="drill-score">{t('verbs.drill.score', { score: s.score, total: s.outOf })}</h2>
        {missedItems.length === 0 ? <p>{t('verbs.drill.perfect')}</p> : null}
      </section>
      {missedItems.length > 0 ? (
        <section className="verb-section">
          <h3 className="verb-section-title">{t('verbs.drill.missed')}</h3>
          <ul className="verb-panel-list" lang="it">
            {missedItems.map((it) => (
              <li key={it.person} className="verb-panel-row">
                <span>{t(personKey(mood, it.person))}</span>
                <strong>{it.primary}</strong>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <div className="drill-actions">
        {missedItems.length > 0 ? (
          <button type="button" className="btn btn-primary" onClick={onRetry}>
            {t('verbs.drill.retry')}
          </button>
        ) : (
          <button type="button" className="btn btn-primary" onClick={onRestart}>
            {t('verbs.drill.again')}
          </button>
        )}
        <button type="button" className="btn" onClick={onExit}>
          {t('verbs.drill.done')}
        </button>
      </div>
    </div>
  );
}
