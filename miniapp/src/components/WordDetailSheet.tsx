import { useCallback, useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { asApiError, type ApiError } from '../api/errors';
import type { CollectionDetail } from '../api/types';
import { useApp } from '../app/context';
import { useI18n } from '../i18n';
import { haptic } from '../telegram';
import { CardSections } from './CardSections';
import { ErrorState } from './ErrorState';
import { ListenButton } from './ListenButton';
import { Sheet } from './Sheet';

interface Props {
  id: string;
  onClose: () => void;
  onRemoved: (id: string) => void;
}

function formatDate(locale: string, iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(d);
}

export function WordDetailSheet({ id, onClose, onRemoved }: Props) {
  const { api, player, toast, reloadMe } = useApp();
  const { t, locale } = useI18n();
  const [detail, setDetail] = useState<CollectionDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setDetail(await api.detail(id));
    } catch (e) {
      setError(asApiError(e));
    }
  }, [api, id]);

  useEffect(() => {
    void load();
  }, [load]);

  // A clip of this word must not start, or go on, after the sheet closes.
  useEffect(() => () => player.stop(), [player]);

  const remove = async () => {
    setRemoving(true);
    try {
      await api.remove(id);
      haptic('success');
      toast(t('detail.removed'));
      onRemoved(id);
      void reloadMe();
      onClose();
    } catch (e) {
      const err = asApiError(e);
      if (err.kind === 'not_found') {
        // Already gone: the list should drop it too.
        onRemoved(id);
        onClose();
        return;
      }
      setRemoving(false);
      setConfirming(false);
      toast(t('detail.removeFailed'), 'error');
    }
  };

  return (
    <Sheet title={detail?.value ?? '…'} onClose={onClose}>
      {error ? <ErrorState error={error} onRetry={() => void load()} compact /> : null}
      {!error && !detail ? <p className="note-line" role="status">{t('common.loading')}</p> : null}
      {detail ? (
        <>
          <ListenButton source={{ expressionId: detail.id, part: 'word' }} text={detail.value} />
          <p className="meta-line">
            {t('collection.stats', { reps: detail.reps, lapses: detail.lapses })}
          </p>
          {formatDate(locale, detail.created_at) ? (
            <p className="meta-line">{t('detail.created', { date: formatDate(locale, detail.created_at) })}</p>
          ) : null}
          {detail.content ? (
            <>
              <CardSections content={detail.content} expressionId={detail.id} />
              {formatDate(locale, detail.generated_at) ? <p className="meta-line">{t('detail.generated', { date: formatDate(locale, detail.generated_at) })}</p> : null}
            </>
          ) : (
            <p className="note-line">{t('detail.noContent')}</p>
          )}
          <div className="sheet-actions">
            {confirming ? (
              <div className="confirm" role="alertdialog" aria-label={t('detail.removeConfirm')}>
                <p className="note-line">{t('detail.removeConfirm')}</p>
                <div className="confirm-row">
                  <button type="button" className="btn btn-danger" onClick={() => void remove()} disabled={removing} data-autofocus>
                    {t('detail.removeYes')}
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={() => setConfirming(false)} disabled={removing}>
                    {t('common.cancel')}
                  </button>
                </div>
              </div>
            ) : (
              <button type="button" className="btn btn-ghost btn-with-icon" onClick={() => setConfirming(true)}>
                <Trash2 size={20} strokeWidth={2.5} aria-hidden="true" />
                {t('detail.remove')}
              </button>
            )}
          </div>
        </>
      ) : null}
    </Sheet>
  );
}
