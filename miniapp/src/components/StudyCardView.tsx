import { useEffect, useRef } from 'react';
import type { Section, StudyCard } from '../api/types';
import { useI18n } from '../i18n';
import type { RefreshStatus } from '../study/reducer';
import { CardSections } from './CardSections';
import { Flag } from './Flag';
import { flagUrl } from './flags';
import { ListenButton } from './ListenButton';
import { useApp } from '../app/context';

/** Size class so long phrases shrink instead of wrapping badly. */
export function fitClass(text: string): string {
  const n = [...text].length;
  if (n <= 10) return 'fit-xl';
  if (n <= 18) return 'fit-l';
  if (n <= 30) return 'fit-m';
  if (n <= 50) return 'fit-s';
  return 'fit-xs';
}

function Badges({ card }: { card: StudyCard }) {
  const { t } = useI18n();
  if (!card.from_storage && !card.older_settings) return null;
  return (
    <div className="badges">
      {card.from_storage ? <span className="badge">{t('study.savedVersion')}</span> : null}
      {card.older_settings ? <span className="badge">{t('study.olderSettings')}</span> : null}
    </div>
  );
}

function QuestionBody({ card }: { card: StudyCard }) {
  const { t } = useI18n();
  const { languageName } = useApp();
  if (card.direction === 'forward') {
    return (
      <>
        <h1 className={`q-word ${fitClass(card.value)}`} dir="auto">
          {card.value}
        </h1>
        <ListenButton expressionId={card.expression_id} part="word" text={card.value} />
        <p className="q-prompt">{t('study.prompt.forward')}</p>
      </>
    );
  }
  const text = card.definition;
  return (
    <>
      <p className="q-prompt">{t('study.prompt.reverse')}</p>
      {text ? (
        <p className={`q-clue ${fitClass(text)}`} dir="auto">
          {text}
        </p>
      ) : (
        <ul className="chips chips-center">
          {card.translations.map((tr, i) => (
            <li className="chip" key={`${tr.label}-${i}`}>
              {flagUrl(tr.country) ? <Flag country={tr.country} name={languageName(tr.country, tr.label)} /> : <span className="chip-label">{tr.label}</span>}
              <span className="chip-text" dir="auto">
                {tr.text}
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

interface StudyCardViewProps {
  card: StudyCard;
  revealed: boolean;
  onReveal: () => void;
  refresh: Record<Section, RefreshStatus>;
  onRefresh: (s: Section) => void;
}

/** Two-faced card with a CSS 3D flip. The hidden face is inert so focus and readers skip it. */
export function StudyCardView({ card, revealed, onReveal, refresh, onRefresh }: StudyCardViewProps) {
  const { t } = useI18n();
  const { player } = useApp();
  const answerHeading = useRef<HTMLHeadingElement>(null);

  // A clip of this card must not start, or go on, over the next card.
  useEffect(() => () => player.stop(), [player, card.delivery_id]);

  useEffect(() => {
    if (revealed) answerHeading.current?.focus({ preventScroll: true });
  }, [revealed]);

  return (
    <div className={revealed ? 'flip is-flipped' : 'flip'}>
      <div className="flip-inner">
        <div className="face face-front" inert={revealed}>
          <Badges card={card} />
          {/* Sits above the button so long text can scroll. Keyboards and screen readers use the button. */}
          <div className="face-front-body" onClick={onReveal}>
            <QuestionBody card={card} />
          </div>
          <button type="button" className="reveal-hit" onClick={onReveal} aria-label={t('study.revealAria')} />
        </div>
        <article className="face face-back" inert={!revealed} aria-live="polite">
          <header className="answer-head">
            <h1 ref={answerHeading} tabIndex={-1} className={`a-word ${fitClass(card.value)}`} dir="auto">
              {card.value}
            </h1>
            <ListenButton expressionId={card.expression_id} part="word" text={card.value} small />
            <Badges card={card} />
          </header>
          <div className="answer-body">
            <CardSections content={card} refresh={refresh} onRefresh={onRefresh} expressionId={card.expression_id} />
          </div>
        </article>
      </div>
    </div>
  );
}
