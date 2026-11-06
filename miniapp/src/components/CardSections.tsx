import type { ReactNode } from 'react';
import { RotateCcw } from 'lucide-react';
import type { AudioPart, Content, Section, Translation } from '../api/types';
import { useApp } from '../app/context';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n/en';
import type { RefreshStatus } from '../study/reducer';
import { Flag } from './Flag';
import { flagUrl } from './flags';
import { ListenButton } from './ListenButton';

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
  listen?: ReactNode;
}

function SectionBlock({ title, children, section, status = 'idle', onRefresh, listen }: SectionBlockProps) {
  const { t } = useI18n();
  const loading = status === 'loading';
  const message: TranslationKey | null =
    status === 'failed' ? 'study.refreshFailed' : status === 'quota' ? 'study.refreshQuota' : status === 'notPending' ? 'study.refreshNotPending' : null;
  return (
    <section className="sec" aria-busy={loading}>
      <div className="sec-head">
        <h3 className="sec-title">{title}</h3>
        <div className="sec-actions">
          {listen}
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

function TranslationChip({ tr, listen }: { tr: Translation; listen?: ReactNode }) {
  const { languageName } = useApp();
  const hasFlag = flagUrl(tr.country) !== null;
  return (
    <li className="chip">
      {hasFlag ? <Flag country={tr.country} name={languageName(tr.country, tr.label)} /> : <span className="chip-label">{tr.label}</span>}
      <span className="chip-text" dir="auto">
        {tr.text}
      </span>
      {listen}
    </li>
  );
}

interface CardSectionsProps {
  content: Content;
  refresh?: Record<Section, RefreshStatus>;
  onRefresh?: (section: Section) => void;
  /** The stored card these sections show. Without it (an unsaved preview) there is nothing to listen to. */
  expressionId?: string;
}

const TRANSLATION_PARTS: AudioPart[] = ['translation_0', 'translation_1'];

/**
 * Definition, translations, example and note. Refresh buttons appear only when `onRefresh` is given,
 * listen buttons only when `expressionId` is.
 */
export function CardSections({ content, refresh, onRefresh, expressionId }: CardSectionsProps) {
  const { t } = useI18n();
  const status = (s: Section): RefreshStatus => refresh?.[s] ?? 'idle';
  // Not while the section is being rewritten: its text is about to change.
  const listen = (section: Section, part: AudioPart | undefined, text: string, small = false) =>
    expressionId && part ? (
      <ListenButton expressionId={expressionId} part={part} text={text} small={small} disabled={status(section) === 'loading'} />
    ) : null;
  return (
    <>
      {content.definition ? (
        <SectionBlock title={t('section.meaning')} section="definition" status={status('definition')} onRefresh={onRefresh} listen={listen('definition', 'definition', content.definition)}>
          <p className="sec-text" dir="auto">
            {content.definition}
          </p>
        </SectionBlock>
      ) : null}
      {content.translations.length > 0 ? (
        <SectionBlock title={t('section.translation')} section="translations" status={status('translations')} onRefresh={onRefresh}>
          <ul className="chips">
            {content.translations.map((tr, i) => (
              <TranslationChip key={`${tr.label}-${i}`} tr={tr} listen={listen('translations', TRANSLATION_PARTS[i], tr.text, true)} />
            ))}
          </ul>
        </SectionBlock>
      ) : null}
      {content.example ? (
        <SectionBlock title={t('section.context')} section="example" status={status('example')} onRefresh={onRefresh} listen={listen('example', 'example', content.example)}>
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
