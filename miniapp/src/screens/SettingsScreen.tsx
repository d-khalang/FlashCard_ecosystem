import { useEffect, useRef, useState } from 'react';
import type { Settings } from '../api/types';
import { useApp } from '../app/context';
import { Field, LanguagePicker, Segmented, Stepper, Switch } from '../components/Controls';
import { ErrorState } from '../components/ErrorState';
import { Mascot } from '../components/Mascot';
import { LOCALES, useI18n, type Locale } from '../i18n';
import type { ScreenProps } from '../navigation';
import { haptic } from '../telegram';
import { formatMinutes } from '../format';

export function SettingsScreen(_props: ScreenProps) {
  const { api, me, meError, reloadMe, setSettings } = useApp();
  const { t, locale, setLocale } = useI18n();
  const [failed, setFailed] = useState(false);

  // Saves run one at a time. On screen: the server's latest settings plus the changes still on their way.
  const pending = useRef<Array<Partial<Settings>>>([]);
  const confirmed = useRef<Settings | null>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());
  if (me && pending.current.length === 0) confirmed.current = me.settings;

  // Pick up changes made elsewhere (the bot) on opening this screen and on coming back to the app.
  useEffect(() => {
    const sync = () => {
      if (!document.hidden && pending.current.length === 0) void reloadMe();
    };
    sync();
    document.addEventListener('visibilitychange', sync);
    return () => document.removeEventListener('visibilitychange', sync);
  }, [reloadMe]);

  if (!me) {
    return (
      <div className="screen">
        {meError ? (
          <ErrorState error={meError} onRetry={() => void reloadMe()} />
        ) : (
          <div className="screen-center" role="status">
            <Mascot name="reading" size="medium" animated />
          </div>
        )}
      </div>
    );
  }

  const s = me.settings;
  const { options } = me;

  const showLatest = () => {
    if (confirmed.current) setSettings(Object.assign({}, confirmed.current, ...pending.current) as Settings);
  };

  /** Optimistic save: show the change at once; if the server refuses, only that change goes away. */
  const change = (patch: Partial<Settings>) => {
    setFailed(false);
    pending.current.push(patch);
    showLatest();
    queue.current = queue.current.then(async () => {
      try {
        confirmed.current = await api.updateSettings(patch);
      } catch {
        setFailed(true);
        haptic('error');
      }
      pending.current.splice(pending.current.indexOf(patch), 1);
      showLatest();
    });
  };

  return (
    <div className="screen">
      <header className="top-bar">
        <h1 className="screen-title">{t('settings.title')}</h1>
      </header>

      {failed ? (
        <p className="inline-error" role="alert">
          {t('settings.saveFailed')}
        </p>
      ) : null}

      <Field label={t('settings.level')}>
        <Segmented
          label={t('settings.level')}
          value={s.target_level}
          options={options.levels.map((l) => ({ value: l, label: l }))}
          onChange={(v) => void change({ target_level: v })}
        />
      </Field>

      <Field label={t('settings.primary')}>
        <LanguagePicker
          label={t('settings.primary')}
          value={s.primary_language}
          options={options.languages}
          onChange={(code) => code && void change({ primary_language: code })}
        />
      </Field>

      <Field label={t('settings.secondary')}>
        <LanguagePicker
          label={t('settings.secondary')}
          value={s.secondary_language}
          // The same language twice adds nothing. A choice already saved stays listed, so the row can name it.
          options={options.languages.filter((l) => l.code !== s.primary_language || l.code === s.secondary_language)}
          noneLabel={t('settings.none')}
          onChange={(code) => void change({ secondary_language: code })}
        />
      </Field>

      <Field label={t('settings.interval')} hint={t('settings.intervalHelp')}>
        <Stepper
          label={t('settings.interval')}
          value={s.review_interval_minutes}
          min={options.min_interval}
          max={options.max_interval}
          format={(v) => formatMinutes(v, t)}
          onCommit={(v) => void change({ review_interval_minutes: v })}
        />
      </Field>

      <Field label={t('settings.mode')} hint={s.review_mode === 'dual' ? t('settings.mode.dual.help') : t('settings.mode.standard.help')}>
        <Segmented
          label={t('settings.mode')}
          value={s.review_mode}
          options={[
            { value: 'standard', label: t('settings.mode.standard') },
            { value: 'dual', label: t('settings.mode.dual') },
          ]}
          onChange={(v) => void change({ review_mode: v })}
        />
      </Field>

      <Field label={t('settings.reminders')}>
        <Switch
          label={t('settings.reminders')}
          description={s.is_active ? t('settings.reminders.on') : t('settings.reminders.off')}
          checked={s.is_active}
          onChange={(v) => void change({ is_active: v })}
        />
        {me.reminders_available ? null : (
          <div className="reminder-hint" role="status">
            <p>{t('settings.reminders.unavailable')}</p>
          </div>
        )}
      </Field>

      <Field label={t('settings.interface')}>
        <Segmented<Locale>
          label={t('settings.interface')}
          value={locale}
          options={LOCALES.map((l) => ({ value: l, label: t(l === 'en' ? 'lang.en' : 'lang.it') }))}
          onChange={setLocale}
        />
      </Field>
    </div>
  );
}
