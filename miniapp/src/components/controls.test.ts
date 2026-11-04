import { describe, expect, it } from 'vitest';
import { formatMinutes } from '../format';
import { translate } from '../i18n';
import { nextInterval } from './Controls';
import { fitClass } from './StudyCardView';

describe('interval stepper', () => {
  it('steps finely when short and coarsely when long, within bounds', () => {
    expect(nextInterval(30, 1, 30, 1440)).toBe(45);
    expect(nextInterval(120, -1, 30, 1440)).toBe(105);
    expect(nextInterval(120, 1, 30, 1440)).toBe(150);
    expect(nextInterval(720, 1, 30, 1440)).toBe(780);
    expect(nextInterval(30, -1, 30, 1440)).toBe(30);
    expect(nextInterval(1440, 1, 30, 1440)).toBe(1440);
  });
});

describe('helpers', () => {
  it('shrinks long phrases', () => {
    expect(fitClass('mare')).toBe('fit-xl');
    expect(fitClass('a seconda delle circostanze particolari del caso')).toBe('fit-s');
  });
  it('formats minutes', () => {
    const t = (k: Parameters<typeof translate>[1], p?: Record<string, string | number>) => translate('en', k, p);
    expect(formatMinutes(45, t)).toBe('45 min');
    expect(formatMinutes(120, t)).toBe('2 h');
    expect(formatMinutes(90, t)).toBe('1 h 30 min');
  });
});
