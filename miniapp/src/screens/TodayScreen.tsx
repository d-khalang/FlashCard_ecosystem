import { useState } from 'react';
import type { Me } from '../api/types';
import { useApp } from '../app/context';
import { AddWord } from '../components/AddWord';
import { ErrorState } from '../components/ErrorState';
import { ImportSheet } from '../components/ImportSheet';
import { Mascot } from '../components/Mascot';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n/en';
import type { ScreenProps } from '../navigation';

const QUOTA_WARN_AT = 3;

/** The quota line is shown only when it matters: nearly used up, or used up. */
export function quotaLine(quota: Me['quota']): { key: TranslationKey; n?: number } | null {
  if (quota.limit === null) return null;
  const left = quota.limit - quota.used;
  if (left <= 0) return { key: 'today.quota.reached' };
  if (left <= QUOTA_WARN_AT) return { key: 'today.quota.left', n: left };
  return null;
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
        <div className="pill">{me.language.name}</div>
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
            {t(quota.key, quota.n === undefined ? undefined : { n: quota.n })}
          </p>
        ) : null}
      </section>
      <AddWord />
      {importing ? <ImportSheet onClose={() => setImporting(false)} /> : null}
    </div>
  );
}
