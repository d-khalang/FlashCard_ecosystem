import { useEffect } from 'react';
import { ChevronLeft, Undo2, X } from 'lucide-react';
import { assertNever, type Grade } from '../api/types';
import { useApp } from '../app/context';
import { ErrorState } from '../components/ErrorState';
import { GradeBar } from '../components/GradeBar';
import { StudyCardView } from '../components/StudyCardView';
import { StudyHint } from '../components/StudyHint';
import { StudyPanel } from '../components/StudyPanel';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n/en';
import { useStudy } from '../study/useStudy';
import { useShortViewport, useStudyHints } from '../study/useStudyHints';
import { haptic, pushBackHandler } from '../telegram';

const NOTICE_TEXT: Record<'gradeFailed' | 'undoNothing' | 'undoFailed', TranslationKey> = {
  gradeFailed: 'study.gradeFailed',
  undoNothing: 'study.undoNothing',
  undoFailed: 'study.undoFailed',
};

interface StudyScreenProps {
  onExit: () => void;
}

export function StudyScreen({ onExit }: StudyScreenProps) {
  const { api, reloadMe } = useApp();
  const { t } = useI18n();
  const study = useStudy(api);
  const { state } = study;

  const exit = () => {
    void reloadMe();
    onExit();
  };

  useEffect(() => pushBackHandler(exit), []);

  // No hint while an error notice shows (a retry must not use one up) or on a very short window.
  const short = useShortViewport();
  const hints = useStudyHints(state.phase, state.notice !== null || short, state.card?.delivery_id ?? null);

  const onGrade = (g: Grade) => {
    haptic(g >= 3 ? 'light' : 'medium');
    hints.onAction('grade');
    study.grade(g);
  };

  let body;
  switch (state.phase) {
    case 'loading':
      body = <StudyPanel mascot="reading" animated live title={undefined} body={t('study.loading')} />;
      break;
    case 'question':
    case 'answer':
      body = state.card ? (
        <StudyCardView
          key={state.card.delivery_id}
          card={state.card}
          revealed={state.phase === 'answer'}
          onReveal={() => {
            haptic('select');
            hints.onAction('reveal');
            study.reveal();
          }}
          refresh={state.refresh}
          onRefresh={(s) => {
            hints.onAction('refresh');
            void study.refresh(s);
          }}
        />
      ) : null;
      break;
    case 'checkpoint':
      body = (
        <StudyPanel mascot="clapping" title={t('study.checkpoint.title')} body={t('study.checkpoint.body', { n: state.reviewed })}>
          <div className="panel-actions">
            <button type="button" className="btn btn-primary" onClick={study.continueSession}>
              {t('study.continue')}
            </button>
            <button type="button" className="btn btn-ghost" onClick={exit}>
              {t('study.finish')}
            </button>
          </div>
        </StudyPanel>
      );
      break;
    case 'finished':
      body = (
        <StudyPanel
          mascot="clapping"
          title={t('study.done.title')}
          body={state.reviewed > 0 ? t('study.done.body', { n: state.reviewed }) : t('study.done.empty')}
        >
          <div className="panel-actions">
            <button type="button" className="btn btn-primary" onClick={exit}>
              {t('study.done.backToday')}
            </button>
          </div>
        </StudyPanel>
      );
      break;
    case 'quota':
      body = (
        <StudyPanel
          mascot="reading"
          title={t('study.quota.title')}
          body={state.quota ? t('quota.message', { limit: state.quota.limit, tier: state.quota.tier }) : undefined}
        >
          <div className="panel-actions">
            <button type="button" className="btn btn-primary" onClick={exit}>
              {t('study.done.backToday')}
            </button>
          </div>
        </StudyPanel>
      );
      break;
    case 'error':
      body = state.error ? <ErrorState error={state.error} onRetry={study.retry} /> : null;
      break;
    default:
      body = assertNever(state.phase);
  }

  return (
    <div className="study">
      <header className="study-head">
        <button type="button" className="text-btn" onClick={exit}>
          <ChevronLeft size={20} strokeWidth={2.8} aria-hidden="true" />
          {t('study.finish')}
        </button>
        <div className="study-count" role="status">
          {t('study.reviewed', { n: state.reviewed })}
        </div>
        <div className="study-head-end">
          {state.undoAvailable ? (
            <button type="button" className="text-btn" onClick={study.undo} disabled={study.busy}>
              <Undo2 size={17} strokeWidth={2.8} aria-hidden="true" />
              {t('study.undo')}
            </button>
          ) : null}
        </div>
      </header>

      {state.notice ? (
        <p className="notice" role="alert">
          <span>{t(NOTICE_TEXT[state.notice])}</span>
          <button type="button" className="icon-btn icon-btn-small" onClick={study.dismissNotice} aria-label={t('common.close')}>
            <X size={18} strokeWidth={2.8} aria-hidden="true" />
          </button>
        </p>
      ) : null}

      <div className="study-main">{body}</div>

      <div className="study-foot">
        <div className="study-hint-slot" role="status">
          {hints.hint && state.card ? <StudyHint text={hints.hint.text} onClose={hints.dismiss} /> : null}
        </div>
        {state.phase === 'answer' ? (
          <GradeBar onGrade={onGrade} />
        ) : state.phase === 'question' && !hints.hint ? (
          <p className="reveal-hint">{t('study.reveal')}</p>
        ) : null}
      </div>
    </div>
  );
}
