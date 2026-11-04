import type { Grade } from '../api/types';
import { useI18n } from '../i18n';

const GRADES: readonly Grade[] = [0, 1, 2, 3, 4, 5];

interface GradeBarProps {
  onGrade: (g: Grade) => void;
}

export function GradeBar({ onGrade }: GradeBarProps) {
  const { t } = useI18n();
  return (
    <div className="grade-bar">
      <div className="grade-captions" aria-hidden="true">
        <span>{t('study.forgot')}</span>
        <span className="grade-question">{t('study.howWell')}</span>
        <span>{t('study.easy')}</span>
      </div>
      <div className="grade-row" role="group" aria-label={t('study.howWell')}>
        {GRADES.map((g) => (
          <button
            key={g}
            type="button"
            className={`grade-btn grade-${g}`}
            onClick={() => onGrade(g)}
            aria-label={`${t('study.gradeAria', { n: g })}${g === 0 ? `, ${t('study.forgot')}` : g === 5 ? `, ${t('study.easy')}` : ''}`}
          >
            {g}
          </button>
        ))}
      </div>
    </div>
  );
}
