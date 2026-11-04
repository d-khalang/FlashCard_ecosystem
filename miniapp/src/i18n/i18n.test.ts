import { describe, expect, it } from 'vitest';
import { en } from './en';
import { it as itDict } from './it';
import { interpolate, pluralKey } from './index';

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('i18n', () => {
  it('has the same keys in en and it', () => {
    expect(Object.keys(itDict).sort()).toEqual(Object.keys(en).sort());
  });

  it('uses the same placeholders in both languages', () => {
    for (const key of Object.keys(en) as Array<keyof typeof en>) {
      expect(placeholders(itDict[key]), key).toEqual(placeholders(en[key]));
    }
  });

  it('has no empty strings', () => {
    for (const dict of [en, itDict]) for (const [k, v] of Object.entries(dict)) expect(v.trim(), k).not.toBe('');
  });

  it('has .one and .other for every plural base', () => {
    for (const key of Object.keys(en)) {
      if (key.endsWith('.one')) expect(en, key).toHaveProperty(key.replace(/\.one$/, '.other'));
    }
  });

  it('interpolates and picks plural forms', () => {
    expect(interpolate('{n} reviewed', { n: 3 })).toBe('3 reviewed');
    expect(pluralKey('en', 'words.ready', 1)).toBe('words.ready.one');
    expect(pluralKey('en', 'words.ready', 12)).toBe('words.ready.other');
    expect(pluralKey('it', 'words.ready', 0)).toBe('words.ready.other');
  });
});
