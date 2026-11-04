import type { Params } from './i18n';
import type { TranslationKey } from './i18n/en';

type T = (key: TranslationKey, params?: Params) => string;

/** 45 -> "45 min", 120 -> "2 h", 90 -> "1 h 30 min". */
export function formatMinutes(total: number, t: T): string {
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return t('duration.minutes', { n: m });
  if (m === 0) return t('duration.hours', { n: h });
  return t('duration.hoursMinutes', { h, m });
}
