import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import type { Api } from '../api/routes';
import type { StudyCard } from '../api/types';
import { AppProvider } from '../app/context';
import { I18nProvider, type Locale } from '../i18n';
import { HINTS_STORAGE_KEY, resetSeenHintsMemory } from '../study/hints';
import { StudyScreen } from './StudyScreen';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
  resetSeenHintsMemory();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

const card = (n: number): StudyCard => ({
  delivery_id: -n,
  expression_id: `e${n}`,
  value: `word ${n}`,
  direction: 'forward',
  from_storage: false,
  older_settings: false,
  definition: 'a meaning',
  translations: [],
  example: 'an example',
  note: null,
});

function studyApi(over: Record<string, unknown> = {}) {
  let n = 0;
  return {
    me: async () => undefined,
    current: vi.fn(async () => ({ card: null, undo_available: false })),
    next: vi.fn(async () => ({ status: 'ready' as const, card: card(++n) })),
    prepare: vi.fn(async () => undefined),
    grade: vi.fn(async () => ({ status: 'graded' as const, undo_available: true })),
    undo: vi.fn(async () => ({ status: 'undone' as const, card: card(1) })),
    refresh: vi.fn(async () => ({ status: 'ready' as const, card: { ...card(1), definition: 'new meaning' } })),
    ...over,
  } as unknown as Api;
}

function open(api: Api, locale: Locale = 'en') {
  return render(
    <I18nProvider initial={locale}>
      <AppProvider api={api} authLost={false}>
        <StudyScreen onExit={() => undefined} />
      </AppProvider>
    </I18nProvider>,
  );
}

const seed = (...ids: string[]) => localStorage.setItem(HINTS_STORAGE_KEY, JSON.stringify(ids));
const stored = () => JSON.parse(localStorage.getItem(HINTS_STORAGE_KEY) ?? '[]') as string[];
const hintEl = () => document.querySelector('.study-hint');
const hintText = () => hintEl()?.textContent ?? null;
const revealBtn = () => screen.findByRole('button', { name: 'Show the answer' });
const reveal = () => fireEvent.click(screen.getByRole('button', { name: 'Show the answer' }));
const gradesGroup = () => screen.findByRole('group', { name: 'How well did you recall it?' });
const grade = (g: number) => fireEvent.click(screen.getByRole('button', { name: new RegExp(`^Grade ${g} of 5`) }));

/** Reveal the current card and wait for the answer side. */
const toAnswer = async () => {
  await revealBtn();
  reveal();
  await gradesGroup();
};

describe('Study hints', () => {
  it('walks through the three hints one at a time, and the refresh hint outlasts grading', async () => {
    open(studyApi());
    await revealBtn();
    expect(document.querySelectorAll('.study-hint').length).toBe(1);
    expect(hintText()).toContain('tap the card');

    reveal(); // doing the thing dismisses hint 1; hint 2 takes its place
    await gradesGroup();
    expect(document.querySelectorAll('.study-hint').length).toBe(1);
    expect(hintText()).toContain('0 means you forgot');

    fireEvent.click(screen.getByRole('button', { name: 'Write a new meaning (uses 1 card)' }));
    expect(hintText()).toContain('0 means you forgot'); // refreshing does not dismiss the grade hint

    grade(4);
    await revealBtn();
    expect(hintEl()).toBeNull(); // the refresh hint waits for an answer

    reveal();
    await gradesGroup();
    expect(hintText()).toContain('circular arrow');

    grade(5); // grading does not dismiss the refresh hint
    await toAnswer();
    expect(hintText()).toContain('circular arrow');

    fireEvent.click(screen.getAllByRole('button', { name: /^Write a new/ })[0]!);
    expect(hintEl()).toBeNull();
    expect(stored().sort()).toEqual(['grades', 'refresh', 'reveal']);

    grade(3);
    await toAnswer();
    expect(hintEl()).toBeNull();
  });

  it('keeps the status region mounted from the start, with the hint inside it', async () => {
    open(studyApi());
    const slot = document.querySelector('.study-hint-slot');
    expect(slot).not.toBeNull();
    expect(slot!.getAttribute('role')).toBe('status');
    await revealBtn();
    expect(document.querySelector('.study-hint-slot')).toBe(slot);
    expect(slot!.contains(hintEl())).toBe(true);
    fireEvent.click(hintEl()!.querySelector('button')!);
    expect(document.querySelector('.study-hint-slot')).toBe(slot);
    expect(hintEl()).toBeNull();
  });

  it('closes with the close button, and the controls keep working', async () => {
    open(studyApi());
    await revealBtn();
    const close = hintEl()!.querySelector('button')!;
    expect(close.getAttribute('aria-label')).toBe('Close');
    fireEvent.click(close);
    expect(hintEl()).toBeNull();
    reveal();
    await gradesGroup();
    expect(hintText()).toContain('0 means you forgot');
  });

  it('does not steal focus when a hint appears', async () => {
    let release: (v: { card: null; undo_available: boolean }) => void = () => undefined;
    const current = vi.fn(() => new Promise<{ card: null; undo_available: boolean }>((r) => (release = r)));
    open(studyApi({ current }));
    const finish = screen.getByRole('button', { name: /Finish/ });
    finish.focus();
    expect(document.activeElement).toBe(finish);
    await waitFor(() => expect(current).toHaveBeenCalled());
    await act(async () => release({ card: null, undo_available: false }));
    await revealBtn();
    expect(hintEl()).not.toBeNull();
    expect(document.activeElement).toBe(finish);
  });

  it('dismisses the refresh hint when a refresh button is tapped', async () => {
    seed('reveal', 'grades');
    open(studyApi());
    await toAnswer();
    expect(hintText()).toContain('circular arrow');
    fireEvent.click(screen.getByRole('button', { name: 'Write a new example (uses 1 card)' }));
    expect(hintEl()).toBeNull();
  });

  it('shows the refresh hint on the next answer after the grade hint, in Italian too', async () => {
    seed('reveal');
    open(studyApi(), 'it');
    await screen.findByRole('button', { name: 'Mostra la risposta' });
    fireEvent.click(screen.getByRole('button', { name: 'Mostra la risposta' }));
    await screen.findByRole('group', { name: 'Com’è andata?' });
    expect(hintText()).toContain('non ricordavi');
    fireEvent.click(screen.getByRole('button', { name: /^Voto 4/ }));
    await screen.findByRole('button', { name: 'Mostra la risposta' });
    fireEvent.click(screen.getByRole('button', { name: 'Mostra la risposta' }));
    await screen.findByRole('group', { name: 'Com’è andata?' });
    expect(hintText()).toContain('freccia circolare');
  });

  describe('a failed grade', () => {
    it('shows no hint with the notice and a retry uses nothing up', async () => {
      seed('reveal', 'grades');
      const grade_ = vi
        .fn()
        .mockRejectedValueOnce(new ApiError('server', 'x'))
        .mockResolvedValue({ status: 'graded', undo_available: true });
      open(studyApi({ grade: grade_ }));
      await toAnswer();
      expect(hintText()).toContain('circular arrow');

      grade(4);
      await screen.findByRole('alert'); // the notice, after the rollback
      expect(hintEl()).toBeNull();
      expect(stored().sort()).toEqual(['grades', 'reveal']);

      grade(4); // retry while the notice is still showing
      await waitFor(() => expect(grade_).toHaveBeenCalledTimes(2));
      await revealBtn();
      expect(stored().sort()).toEqual(['grades', 'reveal']);
      reveal();
      await gradesGroup();
      expect(hintText()).toContain('circular arrow');
    });
  });

  it('after undo does not bring the grade hint back or stack another on the restored answer', async () => {
    seed('reveal');
    open(studyApi());
    await toAnswer();
    expect(hintText()).toContain('0 means you forgot');
    grade(4);
    await revealBtn();
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
    await gradesGroup();
    expect(hintEl()).toBeNull();
    expect(stored().sort()).toEqual(['grades', 'reveal']);
    grade(4);
    await toAnswer();
    expect(hintText()).toContain('circular arrow'); // it comes on a later answer
  });

  it('shows one hint per answer: closing the grade hint does not bring the refresh hint onto the same card', async () => {
    seed('reveal');
    open(studyApi());
    await toAnswer();
    fireEvent.click(hintEl()!.querySelector('button')!);
    expect(hintEl()).toBeNull();
    grade(4);
    await toAnswer();
    expect(hintText()).toContain('circular arrow');
  });

  it('stays dismissed after the screen remounts when storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const first = open(studyApi());
    await revealBtn();
    expect(hintText()).toContain('tap the card');
    reveal();
    await gradesGroup();
    expect(hintText()).toContain('0 means you forgot');
    fireEvent.click(hintEl()!.querySelector('button')!);
    expect(hintEl()).toBeNull();
    first.unmount();

    open(studyApi());
    await revealBtn();
    expect(hintEl()).toBeNull(); // the reveal hint does not return
    reveal();
    await gradesGroup();
    expect(hintText()).toContain('circular arrow'); // the grade hint does not return either
  });

  it('shows nothing and uses nothing up on a very short window', async () => {
    window.matchMedia = vi.fn(() => ({ matches: true, addEventListener: () => undefined, removeEventListener: () => undefined })) as never;
    open(studyApi());
    await revealBtn();
    expect(hintEl()).toBeNull();
    expect(screen.getByText('Tap the card to see the answer')).toBeTruthy(); // the plain line stays
    reveal();
    await gradesGroup();
    expect(hintEl()).toBeNull();
    expect(stored()).toEqual([]);
  });

  it('shows nothing on the finished panel', async () => {
    open(studyApi({ next: vi.fn(async () => ({ status: 'none' as const })) }));
    await screen.findByText('Nothing is due right now.');
    expect(hintEl()).toBeNull();
  });
});
