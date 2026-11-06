import { describe, expect, it } from 'vitest';
import { credits, refillIn } from './credits';

const quota = (used: number, limit: number | null) => ({ used, limit, card_cost: 2, section_cost: 1 });

describe('credits', () => {
  it('is null when nothing limits the user', () => {
    expect(credits(quota(5, null))).toBeNull();
  });
  it('counts what is left and the new cards it pays for', () => {
    expect(credits(quota(6, 40))).toMatchObject({ left: 34, limit: 40, cards: 17, level: 'ok', share: 0.85 });
  });
  it('is low when fewer than two new cards are left', () => {
    expect(credits(quota(37, 40))).toMatchObject({ left: 3, cards: 1, level: 'low' });
    expect(credits(quota(36, 40))?.level).toBe('ok');
  });
  it('is out when a new card no longer fits, even if a part refresh does', () => {
    expect(credits(quota(39, 40))).toMatchObject({ left: 1, cards: 0, level: 'out' });
  });
  it('never goes below zero', () => {
    expect(credits(quota(45, 40))).toMatchObject({ left: 0, share: 0, level: 'out' });
  });
});

describe('refillIn', () => {
  it('counts to the next UTC midnight', () => {
    expect(refillIn(new Date(Date.UTC(2026, 10, 6, 18, 48, 0)))).toEqual({ h: 5, m: 12 });
  });
  it('rounds minutes up', () => {
    expect(refillIn(new Date(Date.UTC(2026, 10, 6, 23, 59, 30)))).toEqual({ h: 0, m: 1 });
  });
});
