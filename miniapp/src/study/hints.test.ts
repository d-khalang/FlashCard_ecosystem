import { afterEach, describe, expect, it, vi } from 'vitest';
import { dictionaries } from '../i18n';
import { afterAction, currentHint, HINTS, HINTS_STORAGE_KEY, loadSeenHints, saveSeenHints, type Hint } from './hints';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const ids = (h: Hint | null) => h?.id ?? null;
const hint = (id: string) => HINTS.find((h) => h.id === id)!;

describe('hint order and phases', () => {
  it('shows the reveal hint first, only on a question', () => {
    const none = new Set<string>();
    expect(ids(currentHint(none, 'question'))).toBe('reveal');
    expect(ids(currentHint(none, 'answer'))).toBeNull();
  });

  it('shows the grade hint on the first answer, then the refresh hint on a later one', () => {
    expect(ids(currentHint(new Set(['reveal']), 'answer'))).toBe('grades');
    expect(ids(currentHint(new Set(['reveal']), 'question'))).toBeNull();
    expect(ids(currentHint(new Set(['reveal', 'grades']), 'question'))).toBeNull();
    expect(ids(currentHint(new Set(['reveal', 'grades']), 'answer'))).toBe('refresh');
  });

  it('shows nothing once every hint is seen', () => {
    const all = new Set(HINTS.map((h) => h.id));
    expect(currentHint(all, 'question')).toBeNull();
    expect(currentHint(all, 'answer')).toBeNull();
  });

  it('shows nothing outside the question and answer phases', () => {
    for (const phase of ['loading', 'checkpoint', 'finished', 'quota', 'error'] as const) {
      expect(currentHint(new Set(), phase)).toBeNull();
      expect(currentHint(new Set(['reveal']), phase)).toBeNull();
    }
  });

  it('skips a revealed card when the reveal hint is unseen, without marking it', () => {
    const none = new Set<string>();
    expect(currentHint(none, 'answer')).toBeNull();
    expect(ids(currentHint(none, 'question'))).toBe('reveal');
  });

  it('has unique ids and a text in every dictionary for each hint', () => {
    for (const h of HINTS) {
      expect(dictionaries.en[h.text]).toBeTruthy();
      expect(dictionaries.it[h.text]).toBeTruthy();
    }
    expect(new Set(HINTS.map((h) => h.id)).size).toBe(HINTS.length);
  });
});

describe('dismissal by action', () => {
  it('reveal dismisses only the reveal hint', () => {
    expect(afterAction(new Set(), hint('reveal'), 'reveal').has('reveal')).toBe(true);
    expect(afterAction(new Set(['reveal']), hint('grades'), 'reveal').has('grades')).toBe(false);
  });

  it('grading dismisses the grade hint and the refresh hint', () => {
    expect(afterAction(new Set(['reveal']), hint('grades'), 'grade').has('grades')).toBe(true);
    expect(afterAction(new Set(['reveal', 'grades']), hint('refresh'), 'grade').has('refresh')).toBe(true);
  });

  it('refreshing dismisses the refresh hint but not the grade hint', () => {
    expect(afterAction(new Set(['reveal']), hint('grades'), 'refresh').has('grades')).toBe(false);
    expect(afterAction(new Set(['reveal', 'grades']), hint('refresh'), 'refresh').has('refresh')).toBe(true);
  });

  it('does nothing when no hint is showing', () => {
    const seen = new Set<string>();
    expect(afterAction(seen, null, 'grade')).toBe(seen);
  });
});

describe('persistence', () => {
  it('round-trips the seen set under the versioned key', () => {
    saveSeenHints(new Set(['reveal', 'grades']));
    expect(HINTS_STORAGE_KEY).toMatch(/\.v1$/);
    expect([...loadSeenHints()].sort()).toEqual(['grades', 'reveal']);
  });

  it('ignores damaged or unknown stored values', () => {
    localStorage.setItem(HINTS_STORAGE_KEY, '{not json');
    expect(loadSeenHints().size).toBe(0);
    localStorage.setItem(HINTS_STORAGE_KEY, '{"a":1}');
    expect(loadSeenHints().size).toBe(0);
    localStorage.setItem(HINTS_STORAGE_KEY, JSON.stringify(['reveal', 7, 'gone']));
    expect([...loadSeenHints()]).toEqual(['reveal']);
  });

  it('does not throw when storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(loadSeenHints().size).toBe(0);
    expect(() => saveSeenHints(new Set(['reveal']))).not.toThrow();
  });
});
