import { describe, expect, it } from 'vitest';
import { quotaLine } from './TodayScreen';

describe('quotaLine', () => {
  it('is hidden when there is no limit or plenty left', () => {
    expect(quotaLine({ used: 5, limit: null })).toBeNull();
    expect(quotaLine({ used: 5, limit: 20 })).toBeNull();
  });
  it('shows what is left when nearly used up', () => {
    expect(quotaLine({ used: 18, limit: 20 })).toEqual({ key: 'today.quota.left', n: 2 });
  });
  it('says so when the limit is reached', () => {
    expect(quotaLine({ used: 20, limit: 20 })).toEqual({ key: 'today.quota.reached' });
  });
});
