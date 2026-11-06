import { useId, useState } from 'react';
import { asApiError, type ApiError } from '../api/errors';
import { assertNever, MAX_IMPORT_CHARS, type ImportResult } from '../api/types';
import { useApp } from '../app/context';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n/en';
import { haptic } from '../telegram';
import { ErrorState } from './ErrorState';
import { Sheet } from './Sheet';

type Outcome = { kind: 'result'; result: ImportResult } | { kind: 'error'; error: ApiError };

function ResultView({ result }: { result: ImportResult }) {
  const { t, plural } = useI18n();
  switch (result.status) {
    case 'imported': {
      const labels = result.items.filter(Boolean);
      return (
        <div role="status">
          <p className="note-line">{plural('import.imported', result.items.length)}</p>
          {labels.length > 0 ? (
            <ul className="chips">
              {labels.map((l, i) => (
                <li className="chip" key={`${l}-${i}`} dir="auto">
                  {l}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      );
    }
    case 'all_duplicates':
    case 'parse_failed':
    case 'nothing_found':
    case 'invalid_language': {
      const key = `import.${result.status}` as TranslationKey;
      return (
        <p className="note-line" role="status">
          {t(key)}
        </p>
      );
    }
    case 'too_long':
      return (
        <p className="note-line" role="status">
          {t('import.too_long', { limit: result.limit })}
        </p>
      );
    case 'too_many':
      return (
        <p className="note-line" role="status">
          {t('import.too_many', { limit: result.limit })}
        </p>
      );
    case 'quota':
      return (
        <p className="note-line" role="status">
          {t('quota.message', { limit: result.limit, tier: result.tier })}
        </p>
      );
    default:
      return assertNever(result);
  }
}

export function ImportSheet({ onClose }: { onClose: () => void }) {
  const { api, reloadMe } = useApp();
  const { t } = useI18n();
  const id = useId();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const submit = async () => {
    setBusy(true);
    setOutcome(null);
    try {
      const result = await api.importText(text);
      setOutcome({ kind: 'result', result });
      if (result.status === 'imported') {
        haptic('success');
        void reloadMe();
      } else if (result.status === 'quota') {
        void reloadMe(); // the shown credits were stale
      }
    } catch (e) {
      setOutcome({ kind: 'error', error: asApiError(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet title={t('import.title')} onClose={onClose}>
      <label htmlFor={id} className="field-label">
        {t('import.label')}
      </label>
      <p className="field-hint">{t('import.hint')}</p>
      <textarea
        id={id}
        data-autofocus
        className="input textarea"
        dir="auto"
        rows={5}
        value={text}
        maxLength={MAX_IMPORT_CHARS}
        onChange={(e) => setText(e.target.value)}
      />
      <p className="counter">{t('import.count', { n: text.length, max: MAX_IMPORT_CHARS })}</p>
      <div className="sheet-actions">
        <button type="button" className="btn btn-primary" onClick={() => void submit()} disabled={busy || !text.trim()} aria-busy={busy}>
          {t('import.submit')}
        </button>
      </div>
      {outcome?.kind === 'result' ? <ResultView result={outcome.result} /> : null}
      {outcome?.kind === 'error' ? <ErrorState error={outcome.error} onRetry={() => void submit()} compact /> : null}
    </Sheet>
  );
}
