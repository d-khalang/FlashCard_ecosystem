import type { Me } from './api/types';

/** Credits left before the chip turns to its low look: enough for one new card and one more. */
export const LOW_AT_CARDS = 2;

export type CreditLevel = 'ok' | 'low' | 'out';

export interface Credits {
  left: number;
  limit: number;
  /** Share of today's credits still left, 0 to 1. */
  share: number;
  /** New cards the credits left still pay for. */
  cards: number;
  /** `out`: not enough for a new card (a part refresh may still fit). */
  level: CreditLevel;
  cardCost: number;
  sectionCost: number;
}

/** Today's credits for display, or null when nothing limits the user (own key, admin). */
export function credits(quota: Me['quota']): Credits | null {
  if (quota.limit === null) return null;
  const limit = quota.limit;
  const left = Math.max(limit - quota.used, 0);
  const cardCost = Math.max(quota.card_cost, 1);
  const level: CreditLevel = left < cardCost ? 'out' : left < cardCost * LOW_AT_CARDS ? 'low' : 'ok';
  return {
    left,
    limit,
    share: limit > 0 ? Math.min(left / limit, 1) : 0,
    cards: Math.floor(left / cardCost),
    level,
    cardCost: quota.card_cost,
    sectionCost: quota.section_cost,
  };
}

/** Milliseconds until the daily counters start again, at 00:00 UTC. */
export function msUntilRefill(now: Date = new Date()): number {
  const next = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  return next - now.getTime();
}

/** Hours and minutes until the refill, minutes rounded up so it never reads 0 min early. */
export function refillIn(now: Date = new Date()): { h: number; m: number } {
  const minutes = Math.ceil(msUntilRefill(now) / 60_000);
  return { h: Math.floor(minutes / 60), m: minutes % 60 };
}
