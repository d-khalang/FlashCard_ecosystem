import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Api } from '../api/routes';
import type { StudyCard } from '../api/types';
import { AppProvider } from '../app/context';
import { I18nProvider } from '../i18n';
import { HINTS_STORAGE_KEY } from '../study/hints';
import { StudyScreen } from './StudyScreen';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
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
    undo: vi.fn(),
    refresh: vi.fn(async () => ({ status: 'ready' as const, card: { ...card(1), definition: 'new meaning' } })),
    ...over,
  } as unknown as Api;
}

function open(api: Api) {
  return render(
    <I18nProvider initial="en">
      <AppProvider api={api} authLost={false}>
        <StudyScreen onExit={() => undefined} />
      </AppProvider>
    </I18nProvider>,
  );
}

const hintEl = () => document.querySelector('.study-hint');
const hintText = () => hintEl()?.textContent ?? null;
const revealBtn = () => screen.findByRole('button', { name: 'Show the answer' });
const reveal = () => fireEvent.click(screen.getByRole('button', { name: 'Show the answer' }));
const gradesGroup = () => screen.findByRole('group', { name: 'How well did you recall it?' });
const grade = (g: number) => fireEvent.click(screen.getByRole('button', { name: new RegExp(`^Grade ${g} of 5`) }));

describe('Study hints', () => {
  it('walks through the three hints one at a time and never shows them again', async () => {
    open(studyApi());
    await revealBtn();
    expect(document.querySelectorAll('.study-hint').length).toBe(1);
    expect(hintEl()?.getAttribute('role')).toBe('status');
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
    expect(hintText()).toContain('round button');
    expect(hintText()).not.toMatch(/card|credit|quota/i);

    grade(5);
    await revealBtn();
    reveal();
    await gradesGroup();
    expect(hintEl()).toBeNull();
    expect(JSON.parse(localStorage.getItem(HINTS_STORAGE_KEY)!).sort()).toEqual(['grades', 'refresh', 'reveal']);
  });

  it('closes with the close button, takes no focus, and the controls keep working', async () => {
    open(studyApi());
    await revealBtn();
    const before = document.activeElement;
    const close = hintEl()!.querySelector('button')!;
    expect(close.getAttribute('aria-label')).toBe('Close');
    fireEvent.click(close);
    expect(hintEl()).toBeNull();
    expect(document.activeElement).toBe(before);
    reveal();
    await gradesGroup();
    expect(hintText()).toContain('0 means you forgot');
  });

  it('dismisses the refresh hint when a refresh button is tapped', async () => {
    localStorage.setItem(HINTS_STORAGE_KEY, JSON.stringify(['reveal', 'grades']));
    open(studyApi());
    await revealBtn();
    expect(hintEl()).toBeNull();
    reveal();
    await gradesGroup();
    expect(hintText()).toContain('round button');
    fireEvent.click(screen.getByRole('button', { name: 'Write a new example (uses 1 card)' }));
    expect(hintEl()).toBeNull();
  });

  it('still works for this page view when storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    open(studyApi());
    await revealBtn();
    expect(hintText()).toContain('tap the card');
    reveal();
    await gradesGroup();
    expect(hintText()).toContain('0 means you forgot');
    grade(3);
    await revealBtn();
    expect(hintEl()).toBeNull();
  });

  it('shows nothing on the finished panel', async () => {
    open(studyApi({ next: vi.fn(async () => ({ status: 'none' as const })) }));
    await screen.findByText('Nothing is due right now.');
    expect(hintEl()).toBeNull();
  });
});
