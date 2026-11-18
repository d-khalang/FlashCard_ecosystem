import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/errors';
import type { Api } from '../../api/routes';
import type { Me } from '../../api/types';
import { AppProvider } from '../../app/context';
import { fixture } from '../../dev/verbFixtures';
import { I18nProvider } from '../../i18n';
import { visibleNav } from '../../navigation';
import type { Drill, LookupFound } from '../../verbs/types';
import { VerbsScreen } from '../VerbsScreen';

afterEach(cleanup);

function verbsApi(overrides: Partial<Api['verbs']> = {}) {
  const verbs: Api['verbs'] = {
    home: vi.fn(async () => fixture('home.json')),
    suggest: vi.fn(async () => fixture('suggest-and.json')),
    lookup: vi.fn(async (q: string) => (q === 'qwerty' ? fixture('lookup-not-found.json') : fixture('lookup-vado.json'))),
    drill: vi.fn(async () => fixture<Drill>('drill-andare-futuro_semplice.json')),
    practice: vi.fn(async () => undefined),
    examples: vi.fn(async () => fixture('examples-unavailable.json')),
    ...overrides,
  };
  const api = { me: () => new Promise<Me>(() => undefined), verbs } as unknown as Api;
  render(
    <I18nProvider initial="en">
      <AppProvider api={api} authLost={false}>
        <VerbsScreen />
      </AppProvider>
    </I18nProvider>,
  );
  return verbs;
}

async function search(q: string) {
  const box = await screen.findByLabelText('Any verb or form');
  fireEvent.change(box, { target: { value: q } });
  fireEvent.submit(box.closest('form')!);
}

describe('Verbs search', () => {
  it('shows recent verbs and collection verbs with meaning', async () => {
    verbsApi();
    expect(await screen.findByRole('button', { name: 'essere' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /svegliarsi\s*to wake up/ })).toBeTruthy();
    // A card without a translation yet: the row shows the verb alone.
    expect(screen.getByRole('button', { name: 'dimenticare' }).textContent).toBe('dimenticare');
  });

  it('shows not found with the query', async () => {
    verbsApi();
    await search('qwerty');
    expect(await screen.findByText('No verb found for “qwerty”')).toBeTruthy();
  });

  it('shows the fuzzy notice', async () => {
    const found = fixture<LookupFound>('lookup-vado.json');
    verbsApi({ lookup: async () => ({ ...found, match: { query: 'andre', kind: 'fuzzy', slots: [], candidates: [] } }) });
    await search('andre');
    expect(await screen.findByText('Showing andare for “andre”')).toBeTruthy();
  });

  it('shows offline as an error with retry', async () => {
    verbsApi({ lookup: async () => Promise.reject(new ApiError('network', 'Failed to fetch')) });
    await search('vado');
    expect(await screen.findByText('You are offline')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });
});

describe('Verbs deck', () => {
  it('opens on the matched tense with the matched slot marked, and moves with the rail and buttons', async () => {
    verbsApi();
    await search('vado');
    const rail = await screen.findByRole('toolbar', { name: 'Tenses' });
    const current = () => within(rail).getByRole('button', { current: true });
    expect(current().getAttribute('aria-label')).toBe('Indicativo Presente, 1 of 15');
    expect(screen.getByText('matches your search')).toBeTruthy();
    expect(screen.getByText('In your collection')).toBeTruthy();

    fireEvent.keyDown(rail, { key: 'ArrowRight' });
    expect(current().getAttribute('aria-label')).toBe('Indicativo Imperfetto, 2 of 15');
    fireEvent.keyDown(rail, { key: 'End' });
    expect(current().getAttribute('aria-label')).toBe('Imperativo Presente, 15 of 15');
    expect(screen.getByRole('button', { name: 'Next tense' })).toHaveProperty('disabled', true);
    fireEvent.click(screen.getByRole('button', { name: 'Previous tense' }));
    expect(current().getAttribute('aria-label')).toBe('Condizionale Passato, 14 of 15');
  });

  it('opens on the first matched tense', async () => {
    const found = fixture<LookupFound>('lookup-vado.json');
    verbsApi({ lookup: async () => ({ ...found, match: { ...found.match, slots: [{ tense_id: 'indicativo-futuro_semplice', person: '1p' }] } }) });
    await search('andremo');
    const rail = await screen.findByRole('toolbar', { name: 'Tenses' });
    expect(within(rail).getByRole('button', { current: true }).getAttribute('aria-label')).toBe('Indicativo Futuro semplice, 4 of 15');
  });

  it('labels persons by mood and shows variants and empty slots', async () => {
    const found = fixture<LookupFound>('lookup-vado.json');
    found.verb.tenses.find((x) => x.id === 'imperativo-presente')!.slots[1]!.forms = [];
    verbsApi({ lookup: async () => found });
    await search('vado');
    await screen.findByRole('toolbar', { name: 'Tenses' });
    const card = (name: RegExp) => screen.getByRole('heading', { name }).closest('section')!;
    const imp = card(/Imperativo\s*Presente/);
    expect(within(imp).getByText('(tu)')).toBeTruthy();
    expect(within(imp).getByText("also: va'")).toBeTruthy();
    expect(within(imp).getByText('(Lei)')).toBeTruthy();
    expect(within(imp).getByText('no form')).toBeTruthy();
    expect(within(card(/Congiuntivo\s*Presente/)).getByText('che lui/lei')).toBeTruthy();
    expect(within(card(/Indicativo\s*Passato prossimo/)).getByText('also: sono andata')).toBeTruthy();
    expect(within(card(/Indicativo\s*Passato remoto/)).getByText('Beyond your level')).toBeTruthy();
  });
});

describe('Verbs deck parts', () => {
  it('renders clitic + stem + ending + enclitic, and hides null principal forms', async () => {
    const found = fixture<LookupFound>('lookup-vado.json');
    found.verb.principal_forms.gerund = null;
    const slot = found.verb.tenses.find((x) => x.id === 'imperativo-presente')!.slots[0]!;
    slot.forms = [
      {
        text: 'vattene',
        primary: true,
        tags: [],
        tts: 'vattene',
        irregular: true,
        parts: { kind: 'simple', clitic: null, stem: 'v', ending: 'a', enclitic: 'ttene', irregular_stem: true, irregular_ending: false },
      },
    ];
    verbsApi({ lookup: async () => found });
    await search('vado');
    await screen.findByRole('toolbar', { name: 'Tenses' });
    const imp = screen.getByRole('heading', { name: /Imperativo\s*Presente/ }).closest('section')!;
    const form = within(imp).getByText('ttene', { exact: false }).closest<HTMLElement>('.slot-form')!;
    expect(form.textContent).toBe('v (irregular)attene');
    expect(within(form).getByText('a').className).toBe('form-ending');
    expect(screen.getByText('to go · essere · andato')).toBeTruthy();
  });
});

describe('Verbs drill', () => {
  it('runs a round, grades per contract and posts practice once', async () => {
    const verbs = verbsApi();
    await search('vado');
    fireEvent.click(await screen.findByRole('button', { name: 'Drill this tense' }));
    const box = await screen.findByLabelText('Your answer');
    const enter = (value?: string) => {
      if (value !== undefined) fireEvent.change(box, { target: { value } });
      fireEvent.submit(box.closest('form')!);
    };
    enter('io andrò');
    expect(screen.getByText('Right: andrò')).toBeTruthy();
    enter();
    enter('andrai');
    enter();
    enter('andra');
    expect(screen.getByText('Right, mind the accent: andrà')).toBeTruthy();
    enter();
    enter('anderemo');
    expect(screen.getByText('Not quite: andremo')).toBeTruthy();
    expect(screen.getByText('Irregular stem: andr-')).toBeTruthy();
    enter();
    fireEvent.click(screen.getByRole('button', { name: 'Show the answer' }));
    expect(screen.getByText('The answer: andrete')).toBeTruthy();
    enter();
    enter('andranno');
    await act(async () => enter());
    expect(screen.getByText('4 of 6 right')).toBeTruthy();
    expect(verbs.practice).toHaveBeenCalledTimes(1);
    expect(verbs.practice).toHaveBeenCalledWith(fixture('practice-request.json'));

    fireEvent.click(screen.getByRole('button', { name: 'Retry the wrong ones' }));
    expect(screen.getByText(/Retry ·/)).toBeTruthy();
    expect(verbs.practice).toHaveBeenCalledTimes(1);
  });

  it('inserts accents at the caret', async () => {
    verbsApi();
    await search('vado');
    fireEvent.click(await screen.findByRole('button', { name: 'Drill this tense' }));
    const box = (await screen.findByLabelText('Your answer')) as HTMLInputElement;
    fireEvent.change(box, { target: { value: 'adr' } });
    box.setSelectionRange(1, 1);
    fireEvent.click(screen.getByRole('button', { name: 'Insert ò' }));
    expect(box.value).toBe('aòdr');
    expect(box.selectionStart).toBe(2);
  });
});

describe('nav', () => {
  it('shows Verbs only when the server turns the feature on', () => {
    const ids = (me: Partial<Me> | null) => visibleNav(me as Me | null).map((n) => n.id);
    expect(ids(null)).not.toContain('verbs');
    expect(ids({})).not.toContain('verbs');
    expect(ids({ features: { verbs: false } })).not.toContain('verbs');
    expect(ids({ features: { verbs: true } })).toEqual(['today', 'collection', 'verbs', 'settings']);
  });
});
