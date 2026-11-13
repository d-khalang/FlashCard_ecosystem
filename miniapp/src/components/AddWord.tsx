import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Plus } from 'lucide-react';
import { asApiError, type ApiError } from '../api/errors';
import { assertNever, MAX_WORD_CHARS, type PreviewResult } from '../api/types';
import { useApp } from '../app/context';
import { useI18n } from '../i18n';
import { haptic } from '../telegram';
import { CardSections } from './CardSections';
import { ErrorState } from './ErrorState';
import { ListenButton } from './ListenButton';
import { Mascot } from './Mascot';
import { Sheet } from './Sheet';

type SaveProblem =
  | { kind: 'error'; error: ApiError }
  | { kind: 'invalid'; suggestions: string[] }
  | { kind: 'too_many'; limit: number };

type Preview = { phase: 'loading' } | { phase: 'done'; result: PreviewResult } | { phase: 'error'; error: ApiError };

export function AddWord() {
  const { api, player, toast, reloadMe } = useApp();
  const { t } = useI18n();
  const inputId = useId();
  const [text, setText] = useState('');
  const [attempt, setAttempt] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<SaveProblem | null>(null);
  const run = useRef(0);

  // A clip of the preview must not play over whatever comes after it.
  useEffect(() => () => player.stop(), [player]);

  const start = async (word: string) => {
    const value = word.trim();
    if (!value) return;
    player.stop();
    const id = ++run.current;
    setAttempt(value);
    setProblem(null);
    setPreview({ phase: 'loading' });
    try {
      const result = await api.preview(value);
      // A ready preview spends credits even if it is never saved, and a quota answer means the count is stale.
      if (result.status === 'ready' || result.status === 'quota') void reloadMe();
      if (run.current === id) setPreview({ phase: 'done', result });
    } catch (e) {
      if (run.current === id) setPreview({ phase: 'error', error: asApiError(e) });
    }
  };

  const close = () => {
    player.stop();
    run.current++;
    setPreview(null);
    setSaving(false);
    setProblem(null);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void start(text);
  };

  /** Saving never repeats the preview (it costs credits): a failed save retries only the save. */
  const save = async (norm: string) => {
    setSaving(true);
    setProblem(null);
    try {
      const r = await api.save(norm);
      switch (r.status) {
        case 'saved':
        case 'already_saved':
          haptic('success');
          toast(r.status === 'saved' ? t('preview.saved') : t('preview.alreadySaved'));
          setText('');
          close();
          void reloadMe();
          return;
        case 'invalid':
          setProblem({ kind: 'invalid', suggestions: r.suggestions });
          break;
        case 'too_many':
          setProblem({ kind: 'too_many', limit: r.limit });
          break;
        default:
          assertNever(r);
      }
    } catch (e) {
      setProblem({ kind: 'error', error: asApiError(e) });
    }
    setSaving(false);
  };

  return (
    <section className="add">
      <label htmlFor={inputId} className="add-label">
        {t('add.label')}
      </label>
      <form className="add-row" onSubmit={submit}>
        <input
          id={inputId}
          className="input"
          dir="auto"
          value={text}
          maxLength={MAX_WORD_CHARS}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('add.placeholder')}
          autoComplete="off"
          autoCapitalize="none"
          enterKeyHint="go"
        />
        <button type="submit" className="btn btn-accent btn-square" aria-label={t('add.button')} disabled={!text.trim()}>
          <Plus size={24} strokeWidth={3} aria-hidden="true" />
        </button>
      </form>
      {preview ? (
        <Sheet title={t('preview.title')} onClose={close}>
          <PreviewBody
            preview={preview}
            saving={saving}
            problem={problem}
            onSave={save}
            onRetry={() => attempt && void start(attempt)}
            onPick={(s) => void start(s)}
          />
        </Sheet>
      ) : null}
    </section>
  );
}

interface PreviewBodyProps {
  preview: Preview;
  saving: boolean;
  problem: SaveProblem | null;
  onSave: (norm: string) => void;
  onRetry: () => void;
  onPick: (s: string) => void;
}

function Suggestions({ items, onPick }: { items: string[]; onPick: (s: string) => void }) {
  const { t } = useI18n();
  if (items.length === 0) return null;
  return (
    <div className="suggest">
      <p className="suggest-title">{t('preview.suggestions')}</p>
      <ul className="chips">
        {items.map((s) => (
          <li key={s}>
            <button type="button" className="chip chip-button" dir="auto" onClick={() => onPick(s)}>
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PreviewBody({ preview, saving, problem, onSave, onRetry, onPick }: PreviewBodyProps) {
  const { t } = useI18n();
  if (preview.phase === 'loading') {
    return (
      <div className="sheet-center" role="status">
        <Mascot name="reading" size="medium" animated />
        <p>{t('preview.loading')}</p>
      </div>
    );
  }
  if (preview.phase === 'error') {
    return <ErrorState error={preview.error} onRetry={onRetry} compact />;
  }
  const r = preview.result;
  switch (r.status) {
    case 'ready':
      return (
        <>
          <div className="preview-head">
            <h3 className="preview-word" dir="auto">
              {r.norm}
            </h3>
            {r.audio?.word ? <ListenButton source={{ speechKey: r.audio.word }} text={r.norm} /> : null}
          </div>
          <CardSections content={r.content} speechKeys={r.audio ?? {}} />
          {problem?.kind === 'error' ? <ErrorState error={problem.error} onRetry={() => onSave(r.norm)} compact /> : null}
          {problem?.kind === 'invalid' ? (
            <div role="alert">
              <p className="note-line">{t('preview.saveInvalid')}</p>
              <Suggestions items={problem.suggestions} onPick={onPick} />
            </div>
          ) : null}
          {problem?.kind === 'too_many' ? (
            <p className="note-line" role="alert">
              {t('preview.tooMany', { limit: problem.limit })}
            </p>
          ) : null}
          <div className="sheet-actions">
            <button type="button" className="btn btn-primary" onClick={() => onSave(r.norm)} disabled={saving}>
              {t('preview.save')}
            </button>
            <button type="button" className="btn btn-ghost" onClick={onRetry} disabled={saving}>
              {t('preview.tryAgain')}
            </button>
          </div>
        </>
      );
    case 'unclear':
      return (
        <div role="status">
          <p className="note-line">{t('preview.unclear')}</p>
          {r.note ? (
            <p className="note-line" dir="auto">
              {r.note}
            </p>
          ) : null}
          <Suggestions items={r.suggestions} onPick={onPick} />
        </div>
      );
    case 'invalid':
      return (
        <div role="status">
          <p className="note-line">{t('preview.invalid')}</p>
          <Suggestions items={r.suggestions} onPick={onPick} />
        </div>
      );
    case 'quota':
      return (
        <p className="note-line" role="status">
          {t('quota.message', { limit: r.limit, tier: r.tier })}
        </p>
      );
    default:
      return assertNever(r);
  }
}
