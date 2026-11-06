import { useState } from 'react';
import type { Me } from '../api/types';
import { useApp } from '../app/context';
import { AddWord } from '../components/AddWord';
import { CreditChip } from '../components/CreditChip';
import { credits, refillIn } from '../credits';
import { ErrorState } from '../components/ErrorState';
import { ImportSheet } from '../components/ImportSheet';
import { Mascot } from '../components/Mascot';
import { useI18n, type Params } from '../i18n';
import type { TranslationKey } from '../i18n/en';
import type { ScreenProps } from '../navigation';

/** The credit line under the hero is shown only when it matters: few credits left, or none for a new card. */
export function quotaLine(quota: Me['quota'], now: Date = new Date()): { key: TranslationKey; params: Params } | null {
  const c = credits(quota);
  if (!c || c.level === 'ok') return null;
  if (c.level === 'low') return { key: 'today.quota.low', params: { n: c.left } };
  return { key: 'today.quota.out', params: refillIn(now) };
}

export function TodayScreen({ onStudy }: ScreenProps) {
  const { me, meError, reloadMe } = useApp();
  const { t, plural } = useI18n();
  const [importing, setImporting] = useState(false);

  if (!me) {
    return (
      <div className="screen">
        {meError ? (
          <ErrorState error={meError} onRetry={() => void reloadMe()} />
        ) : (
          <div className="screen-center" role="status">
            <Mascot name="reading" size="medium" animated />
            <span className="sr-only">{t('common.loading')}</span>
          </div>
        )}
      </div>
    );
  }

  const { total, ready, pending } = me.words;
  const quota = quotaLine(me.quota);

  return (
    <div className="screen">
      <header className="top-bar">
        <div className="brand">{t('app.brand')}</div>
        <div className="top-bar-end">
          <CreditChip quota={me.quota} />
          <div className="pill">{me.language.name}</div>
        </div>
      </header>
      <section className="hero">
        {total === 0 && !pending ? (
          <>
            <Mascot name="waving" />
            <h1 className="hero-title">{t('today.empty.title')}</h1>
            <p className="hero-body">{t('today.empty.body')}</p>
            <button type="button" className="btn btn-accent btn-wide" onClick={() => setImporting(true)}>
              {t('add.import')}
            </button>
          </>
        ) : ready === 0 && !pending ? (
          <>
            <Mascot name="clapping" />
            <h1 className="hero-title">{t('today.caughtUp.title')}</h1>
            <p className="hero-body">{t('today.caughtUp.body')}</p>
          </>
        ) : (
          <>
            <Mascot name="waving" />
            <h1 className="hero-title">{ready > 0 ? plural('words.ready', ready) : t('today.pending.title')}</h1>
            <div className="grow" />
            <button type="button" className="btn btn-primary btn-wide" onClick={onStudy}>
              {pending ? t('today.continue') : t('today.study')}
            </button>
          </>
        )}
        {quota ? (
          <p className="quota-line" role="status">
            {t(quota.key, quota.params)}
          </p>
        ) : null}
      </section>
      <AddWord />
      {importing ? <ImportSheet onClose={() => setImporting(false)} /> : null}
    </div>
  );
}
