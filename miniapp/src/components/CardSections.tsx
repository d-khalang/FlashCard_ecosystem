import type { ReactNode } from 'react';
import { RotateCcw } from 'lucide-react';
import type { Content, Section, Translation } from '../api/types';
import { useApp } from '../app/context';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n/en';
import type { RefreshStatus } from '../study/reducer';
import { Flag } from './Flag';
import { flagUrl } from './flags';

const REFRESH_LABEL: Record<Section, TranslationKey> = {
  definition: 'study.refresh.meaning',
  translations: 'study.refresh.translation',
  example: 'study.refresh.example',
};

interface SectionBlockProps {
  title: string;
  children: ReactNode;
  section?: Section;
  status?: RefreshStatus;
  onRefresh?: (section: Section) => void;
}

function SectionBlock({ title, children, section, status = 'idle', onRefresh }: SectionBlockProps) {
  const { t } = useI18n();
  const loading = status === 'loading';
  const message: TranslationKey | null =
    status === 'failed' ? 'study.refreshFailed' : status === 'quota' ? 'study.refreshQuota' : status === 'notPending' ? 'study.refreshNotPending' : null;
  return (
    <section className="sec" aria-busy={loading}>
      <div className="sec-head">
        <h3 className="sec-title">{title}</h3>
        {section && onRefresh ? (
          <button
            type="button"
            className="icon-btn refresh-btn"
            onClick={() => onRefresh(section)}
            disabled={loading}
            aria-label={t(REFRESH_LABEL[section])}
            title={t(REFRESH_LABEL[section])}
          >
            <RotateCcw size={19} strokeWidth={2.5} aria-hidden="true" className={loading ? 'spin' : undefined} />
          </button>
        ) : null}
      </div>
      <div className={loading ? 'sec-body is-pulsing' : 'sec-body'}>{children}</div>
      {loading ? <span className="sr-only">{t('study.refreshing')}</span> : null}
      {message ? (
        <p className="sec-msg" role="status">
          {t(message)}
        </p>
      ) : null}
    </section>
  );
}

function TranslationChip({ tr }: { tr: Translation }) {
  const { languageName } = useApp();
  const hasFlag = flagUrl(tr.country) !== null;
  return (
    <li className="chip">
      {hasFlag ? <Flag country={tr.country} name={languageName(tr.country, tr.label)} /> : <span className="chip-label">{tr.label}</span>}
      <span className="chip-text" dir="auto">
        {tr.text}
      </span>
    </li>
  );
}

interface CardSectionsProps {
  content: Content;
  refresh?: Record<Section, RefreshStatus>;
  onRefresh?: (section: Section) => void;
}

/** Definition, translations, example and note. Refresh buttons appear only when `onRefresh` is given. */
export function CardSections({ content, refresh, onRefresh }: CardSectionsProps) {
  const { t } = useI18n();
  const status = (s: Section): RefreshStatus => refresh?.[s] ?? 'idle';
  return (
    <>
      {content.definition ? (
        <SectionBlock title={t('section.meaning')} section="definition" status={status('definition')} onRefresh={onRefresh}>
          <p className="sec-text" dir="auto">
            {content.definition}
          </p>
        </SectionBlock>
      ) : null}
      {content.translations.length > 0 ? (
        <SectionBlock title={t('section.translation')} section="translations" status={status('translations')} onRefresh={onRefresh}>
          <ul className="chips">
            {content.translations.map((tr, i) => (
              <TranslationChip key={`${tr.label}-${i}`} tr={tr} />
            ))}
          </ul>
        </SectionBlock>
      ) : null}
      {content.example ? (
        <SectionBlock title={t('section.context')} section="example" status={status('example')} onRefresh={onRefresh}>
          <p className="sec-text example-panel" dir="auto">
            {content.example}
          </p>
        </SectionBlock>
      ) : null}
      {content.note ? (
        <SectionBlock title={t('section.note')}>
          <p className="sec-text sec-note" dir="auto">
            {content.note}
          </p>
        </SectionBlock>
      ) : null}
    </>
  );
}
