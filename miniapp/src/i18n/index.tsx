import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { en, type TranslationKey } from './en';
import { it } from './it';
import { telegramLanguage } from '../telegram';

export type Locale = 'en' | 'it';
export const LOCALES: readonly Locale[] = ['en', 'it'];
export const dictionaries: Record<Locale, Record<TranslationKey, string>> = { en, it };

/** Keys that have a `.one` and `.other` form. */
export type PluralBase = TranslationKey extends infer K
  ? K extends `${infer B}.one`
    ? B
    : never
  : never;

export type Params = Record<string, string | number>;

const STORAGE_KEY = 'kartino.locale';

export function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const v = params[name];
    return v === undefined ? whole : String(v);
  });
}

export function translate(locale: Locale, key: TranslationKey, params?: Params): string {
  return interpolate(dictionaries[locale][key], params);
}

export function pluralKey(locale: Locale, base: PluralBase, n: number): TranslationKey {
  const category = new Intl.PluralRules(locale).select(n);
  return `${base}.${category === 'one' ? 'one' : 'other'}` as TranslationKey;
}

export function initialLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'en' || saved === 'it') return saved;
  } catch {
    /* storage can be unavailable */
  }
  const lang = (telegramLanguage() ?? navigator.language ?? 'en').toLowerCase();
  return lang.startsWith('it') ? 'it' : 'en';
}

interface I18n {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: TranslationKey, params?: Params) => string;
  plural: (base: PluralBase, n: number, params?: Params) => string;
}

const Ctx = createContext<I18n | null>(null);

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Locale }) {
  const [locale, setLocaleState] = useState<Locale>(initial ?? initialLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo<I18n>(
    () => ({
      locale,
      setLocale,
      t: (key, params) => translate(locale, key, params),
      plural: (base, n, params) => translate(locale, pluralKey(locale, base, n), { n, ...params }),
    }),
    [locale, setLocale],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error('useI18n outside I18nProvider');
  return v;
}
