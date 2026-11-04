import { TriangleAlert, WifiOff } from 'lucide-react';
import type { ApiError } from '../api/errors';
import { useI18n } from '../i18n';
import { errorCopy } from './errorText';

interface ErrorStateProps {
  error: ApiError;
  onRetry?: () => void;
  /** Compact, inline variant for failures inside a screen. */
  compact?: boolean;
}

export function ErrorState({ error, onRetry, compact = false }: ErrorStateProps) {
  const { t } = useI18n();
  const copy = errorCopy(error);
  const Icon = error.kind === 'network' ? WifiOff : TriangleAlert;
  return (
    <div className={compact ? 'error-state error-compact' : 'error-state'} role="alert">
      <Icon size={compact ? 22 : 40} strokeWidth={2.4} aria-hidden="true" />
      <h2 className="error-title">{t(copy.title)}</h2>
      <p className="error-body">{t(copy.body)}</p>
      {copy.retryable && onRetry ? (
        <button type="button" className="btn btn-accent" onClick={onRetry}>
          {t('common.retry')}
        </button>
      ) : null}
    </div>
  );
}
