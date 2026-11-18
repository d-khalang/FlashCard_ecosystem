import { describe, expect, it } from 'vitest';
import { fixture } from '../dev/verbFixtures';
import { drillReducer, practiceBody, score, startDrill, type DrillAction, type DrillState } from './drillSession';
import type { Drill } from './types';

const futuro = fixture<Drill>('drill-andare-futuro_semplice.json');
const run = (s: DrillState, ...actions: DrillAction[]) => actions.reduce(drillReducer, s);
const answer = (input: string): DrillAction[] => [{ type: 'check', input }, { type: 'next' }];

describe('drill session', () => {
  it('grades a round and builds the practice body', () => {
    const s = run(
      startDrill(futuro),
      ...answer('io andrò'),
      ...answer('andrai'),
      ...answer('andra'), // accent: counts
      ...answer('anderemo'),
      { type: 'show' },
      { type: 'next' },
      ...answer('andranno'),
    );
    expect(s.phase).toBe('summary');
    expect(score(s)).toEqual({ score: 4, outOf: 6, missed: ['1p', '2p'] });
    expect(practiceBody(s)).toEqual(fixture('practice-request.json'));
  });

  it('handles Enter by phase, so a quick double Enter checks then moves on', () => {
    const s = run(startDrill(futuro), { type: 'enter', input: 'andrò' }, { type: 'enter', input: 'andrò' });
    expect(s.index).toBe(1);
    expect(s.phase).toBe('answer');
    expect(s.answers).toHaveLength(1);
  });

  it('ignores an empty check and only moves on after feedback', () => {
    let s = run(startDrill(futuro), { type: 'check', input: '  ' }, { type: 'next' });
    expect(s.phase).toBe('answer');
    expect(s.index).toBe(0);
    s = drillReducer(s, { type: 'show' });
    expect(s.answers[0]).toEqual({ verdict: { result: 'wrong' }, shown: true });
  });

  it('retries only the wrong ones, without sending practice again', () => {
    let s = run(startDrill(futuro), ...['andrò', 'x', 'andrà', 'andremo', 'y', 'andranno'].flatMap(answer));
    s = drillReducer(s, { type: 'retryWrong' });
    expect(s.round.map((i) => i.person)).toEqual(['2s', '2p']);
    s = run(s, ...answer('andrai'), ...answer('andrete'));
    expect(score(s).score).toBe(2);
    expect(practiceBody(s)).toBeNull();
  });
});
