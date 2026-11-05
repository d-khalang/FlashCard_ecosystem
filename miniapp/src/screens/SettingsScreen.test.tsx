import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Api } from '../api/routes';
import type { Me, Settings } from '../api/types';
import { AppProvider } from '../app/context';
import { I18nProvider } from '../i18n';
import { SettingsScreen } from './SettingsScreen';

afterEach(cleanup);

const SETTINGS: Settings = {
  target_level: 'B1',
  primary_language: 'en',
  secondary_language: null,
  review_mode: 'standard',
  review_interval_minutes: 120,
  is_active: true,
};

const me = (over: Partial<Settings> = {}): Me => ({
  language: { code: 'it', name: 'Italiano', country: null },
  settings: { ...SETTINGS, ...over },
  quota: { used: 0, limit: 20 },
  words: { total: 10, ready: 0, pending: false },
  reminders_available: true,
  options: {
    levels: ['B1', 'B2'],
    languages: [
      { code: 'en', name: 'English', country: null },
      { code: 'fa', name: 'Persian', country: null },
    ],
    min_interval: 15,
    max_interval: 240,
  },
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function setup(api: Partial<Api>) {
  render(
    <I18nProvider initial="en">
      <AppProvider api={{ me: async () => me(), ...api } as Api} authLost={false}>
        <SettingsScreen {...({} as Parameters<typeof SettingsScreen>[0])} />
      </AppProvider>
    </I18nProvider>,
  );
  await screen.findByRole('radio', { name: 'B2' });
}

const checked = (name: string) => screen.getByRole('radio', { name }).getAttribute('aria-checked');

describe('saving settings', () => {
  it('runs saves in order and keeps a newer change on screen while an older one answers', async () => {
    const first = deferred<Settings>();
    const second = deferred<Settings>();
    const updateSettings = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    await setup({ updateSettings });

    fireEvent.click(screen.getByRole('radio', { name: 'B2' }));
    fireEvent.click(screen.getByRole('radio', { name: 'Both ways' }));
    await waitFor(() => expect(updateSettings).toHaveBeenCalledTimes(1));

    await act(async () => first.resolve({ ...SETTINGS, target_level: 'B2' }));
    expect(checked('Both ways')).toBe('true');
    await waitFor(() => expect(updateSettings).toHaveBeenCalledTimes(2));

    await act(async () => second.resolve({ ...SETTINGS, target_level: 'B2', review_mode: 'dual' }));
    expect(checked('B2')).toBe('true');
    expect(checked('Both ways')).toBe('true');
  });

  it('shows what the server says about other settings', async () => {
    const updateSettings = vi.fn(async () => ({ ...SETTINGS, target_level: 'B2', review_mode: 'dual' as const }));
    await setup({ updateSettings });

    await act(async () => fireEvent.click(screen.getByRole('radio', { name: 'B2' })));

    expect(checked('Both ways')).toBe('true');
  });

  it('takes back only the change that failed', async () => {
    const first = deferred<Settings>();
    const updateSettings = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({ ...SETTINGS, review_mode: 'dual' });
    await setup({ updateSettings });

    fireEvent.click(screen.getByRole('radio', { name: 'B2' }));
    fireEvent.click(screen.getByRole('radio', { name: 'Both ways' }));
    await act(async () => first.reject(new Error('no')));

    await waitFor(() => expect(updateSettings).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(checked('B1')).toBe('true'));
    expect(checked('Both ways')).toBe('true');
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  it('reloads when the user comes back to the app', async () => {
    const meApi = vi.fn(async () => me());
    await setup({ me: meApi });
    const before = meApi.mock.calls.length;

    await act(async () => document.dispatchEvent(new Event('visibilitychange')));

    expect(meApi.mock.calls.length).toBe(before + 1);
  });
});

describe('the secondary language', () => {
  const openSecondary = () => fireEvent.click(screen.getByRole('button', { name: /^Second translation/i }));

  it('does not offer the primary language', async () => {
    await setup({});
    openSecondary();
    const sheet = within(screen.getByRole('dialog'));
    expect(sheet.getByRole('radio', { name: 'Persian' })).toBeTruthy();
    expect(sheet.queryByRole('radio', { name: 'English' })).toBeNull();
  });
});
