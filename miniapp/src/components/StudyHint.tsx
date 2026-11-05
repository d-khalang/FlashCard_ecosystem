import { Lightbulb, X } from 'lucide-react';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n/en';

interface StudyHintProps {
  text: TranslationKey;
  onClose: () => void;
}

/** A passive tip in the page flow. Never takes focus and never covers the study controls. */
export function StudyHint({ text, onClose }: StudyHintProps) {
  const { t } = useI18n();
  return (
    <div className="study-hint" role="status">
      <span className="study-hint-icon" aria-hidden="true">
        <Lightbulb size={18} strokeWidth={2.6} />
      </span>
      <p className="study-hint-text" dir="auto">
        {t(text)}
      </p>
      <button type="button" className="icon-btn study-hint-close" onClick={onClose} aria-label={t('common.close')}>
        <X size={20} strokeWidth={2.8} aria-hidden="true" />
      </button>
    </div>
  );
}
