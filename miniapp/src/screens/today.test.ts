import { describe, expect, it } from 'vitest';
import { quotaLine } from './TodayScreen';

const quota = (used: number, limit: number | null) => ({ used, limit, card_cost: 2, section_cost: 1 });

describe('quotaLine', () => {
  it('is hidden when there is no limit or plenty left', () => {
    expect(quotaLine(quota(5, null))).toBeNull();
    expect(quotaLine(quota(5, 20))).toBeNull();
  });
  it('shows the credits left when few are left', () => {
    expect(quotaLine(quota(17, 20))).toEqual({ key: 'today.quota.low', params: { n: 3 } });
  });
  it('says when a new card no longer fits, and when the credits refill', () => {
    const now = new Date(Date.UTC(2026, 10, 6, 18, 48));
    expect(quotaLine(quota(19, 20), now)).toEqual({ key: 'today.quota.out', params: { h: 5, m: 12 } });
  });
});
