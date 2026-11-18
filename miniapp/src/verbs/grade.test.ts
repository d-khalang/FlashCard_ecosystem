import { describe, expect, it } from 'vitest';
import { fixture } from '../dev/verbFixtures';
import { gradeAnswer, normalizeAnswer, stripPrefix, type Verdict } from './grade';
import type { AcceptedNote, Drill, DrillItem } from './types';

const futuro = fixture<Drill>('drill-andare-futuro_semplice.json');
const passato = fixture<Drill>('drill-andare-passato_prossimo.json');
const item = (d: Drill, person: string) => d.items.find((i) => i.person === person)!;

const imperativo: DrillItem = {
  person: '2s',
  primary: 'vai',
  accepted: [
    { text: 'vai', note: null },
    { text: "va'", note: 'variant' },
  ],
  accepted_plain: ['vai', "va'"],
  hint: { kind: 'irregular_form' },
};
const reflexive: DrillItem = {
  person: '1s',
  primary: 'mi alzo',
  accepted: [{ text: 'mi alzo', note: null }],
  accepted_plain: ['mi alzo'],
  hint: null,
};

const right = (note: AcceptedNote | null = null): Verdict => ({ result: 'right', note });
const accent: Verdict = { result: 'accent' };
const wrong: Verdict = { result: 'wrong' };

describe('gradeAnswer (contract §4)', () => {
  const cases: Array<[string, string, DrillItem, Drill['strip_prefixes'], Verdict]> = [
    ['exact', 'andrò', item(futuro, '1s'), futuro.strip_prefixes, right()],
    ['subject pronoun', 'io andrò', item(futuro, '1s'), futuro.strip_prefixes, right()],
    ['case, spaces', '  Io   ANDRÒ ', item(futuro, '1s'), futuro.strip_prefixes, right()],
    ['decomposed accent (NFD input)', 'andrò', item(futuro, '1s'), futuro.strip_prefixes, right()],
    ['missing accent', 'andro', item(futuro, '1s'), futuro.strip_prefixes, accent],
    ['missing accent with pronoun', 'io andro', item(futuro, '1s'), futuro.strip_prefixes, accent],
    ['wrong accent direction', 'andró', item(futuro, '1s'), futuro.strip_prefixes, accent],
    ['lui/lei', 'lei andrà', item(futuro, '3s'), futuro.strip_prefixes, right()],
    ['wrong form', 'anderemo', item(futuro, '1p'), futuro.strip_prefixes, wrong],
    ['other person', 'andrai', item(futuro, '1s'), futuro.strip_prefixes, wrong],
    ['empty', '   ', item(futuro, '1s'), futuro.strip_prefixes, wrong],
    ['pronoun only', 'io', item(futuro, '1s'), futuro.strip_prefixes, wrong],
    ['compound', 'sono andato', item(passato, '1s'), passato.strip_prefixes, right()],
    ['feminine note', 'sono andata', item(passato, '1s'), passato.strip_prefixes, right('feminine')],
    ['feminine with pronoun', 'io sono andata', item(passato, '1s'), passato.strip_prefixes, right('feminine')],
    ['è without accent', 'e andato', item(passato, '3s'), passato.strip_prefixes, accent],
    ['è', 'lui è andato', item(passato, '3s'), passato.strip_prefixes, right()],
    ['typographic apostrophe', 'va’', imperativo, ['tu'], right('variant')],
    ['clitic required', 'alzo', reflexive, ['io'], wrong],
    ['clitic with pronoun', 'io mi alzo', reflexive, ['io'], right()],
  ];

  it.each(cases)('%s: %j', (_name, input, it_, prefixes, expected) => {
    expect(gradeAnswer(input, it_, prefixes)).toEqual(expected);
  });
});

describe('helpers', () => {
  it('normalizes', () => {
    expect(normalizeAnswer(' Sono\tANDATO ')).toBe('sono andato');
  });

  it('strips the first matching prefix only, and only before a space', () => {
    const prefixes = ['che io', 'io', 'che'];
    expect(stripPrefix('che io vada', prefixes)).toBe('vada');
    expect(stripPrefix('che vada', prefixes)).toBe('vada');
    expect(stripPrefix('iovado', prefixes)).toBe('iovado');
    expect(stripPrefix('io io vado', prefixes)).toBe('io vado');
  });
});
