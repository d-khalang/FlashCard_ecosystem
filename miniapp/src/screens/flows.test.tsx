import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import type { Api } from '../api/routes';
import type { Me } from '../api/types';
import { AppProvider } from '../app/context';
import { ClipPlayer } from '../audio/player';
import { AddWord } from '../components/AddWord';
import { Stepper } from '../components/Controls';
import { I18nProvider } from '../i18n';
import { TodayScreen } from './TodayScreen';

afterEach(cleanup);

const baseMe = (words: Partial<Me['words']>): Me => ({
  language: { code: 'it', name: 'Italiano', country: null },
  settings: { target_level: 'B1', primary_language: 'en', secondary_language: null, review_mode: 'standard', review_interval_minutes: 120, is_active: true },
  quota: { used: 0, limit: 20, card_cost: 2, section_cost: 1 },
  words: { total: 10, ready: 0, pending: false, ...words },
  reminders_available: true,
  options: { levels: ['B1'], languages: [{ code: 'en', name: 'English', country: null }], min_interval: 30, max_interval: 1440 },
});

function wrap(api: Partial<Api>, children: ReactNode) {
  return render(
    <I18nProvider initial="en">
      <AppProvider api={api as Api} authLost={false}>
        {children}
      </AppProvider>
    </I18nProvider>,
  );
}

const readyPreview = (norm: string) => async () => ({
  status: 'ready' as const,
  norm,
  content: { definition: 'd', translations: [], example: null, note: null },
});

describe('Today', () => {
  it('never says caught up while a card is pending, and offers to resume it', async () => {
    wrap({ me: async () => baseMe({ ready: 0, pending: true }) }, <TodayScreen onStudy={() => undefined} />);
    expect(await screen.findByRole('button', { name: 'Continue your card' })).toBeTruthy();
    expect(screen.queryByText('All caught up')).toBeNull();
  });

  it('says caught up only when nothing is ready or pending', async () => {
    wrap({ me: async () => baseMe({ ready: 0, pending: false }) }, <TodayScreen onStudy={() => undefined} />);
    expect(await screen.findByText('All caught up')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Study now' })).toBeNull();
  });

  it('shows Study now when words are ready', async () => {
    wrap({ me: async () => baseMe({ ready: 3 }) }, <TodayScreen onStudy={() => undefined} />);
    expect(await screen.findByRole('button', { name: 'Study now' })).toBeTruthy();
  });
});

describe('AddWord credits', () => {
  it('reloads the credits after a ready preview, even if the word is never saved', async () => {
    const me = vi.fn(async () => baseMe({}));
    wrap({ me, preview: vi.fn(readyPreview('mare')) } as Partial<Api>, <AddWord />);
    await waitFor(() => expect(me).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText('Add a word'), { target: { value: 'mare' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await screen.findByRole('button', { name: 'Save' });
    await waitFor(() => expect(me).toHaveBeenCalledTimes(2));
  });
});

describe('AddWord save', () => {
  it('retries only the save after a failed save, never the preview', async () => {
    const preview = vi.fn(readyPreview('mare'));
    const save = vi.fn().mockRejectedValueOnce(new ApiError('network', 'x')).mockResolvedValueOnce({ status: 'saved' });
    wrap({ me: async () => baseMe({}), preview, save } as Partial<Api>, <AddWord />);
    fireEvent.change(screen.getByLabelText('Add a word'), { target: { value: 'mare' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Save' }));
    await screen.findByRole('alert');
    // Two "Try again" buttons exist: the error block's (first, retries the save) and the preview's.
    const buttons = screen.getAllByRole('button', { name: 'Try again' });
    expect(buttons.length).toBe(2);
    await act(async () => fireEvent.click(buttons[0]!));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(preview).toHaveBeenCalledTimes(1);
  });

  it('shows suggestions when the save is invalid and a limit message for too_many', async () => {
    const preview = vi.fn(readyPreview('zz'));
    const save = vi.fn().mockResolvedValueOnce({ status: 'invalid', suggestions: ['zaino'] }).mockResolvedValueOnce({ status: 'too_many', limit: 500 });
    wrap({ me: async () => baseMe({}), preview, save } as Partial<Api>, <AddWord />);
    fireEvent.change(screen.getByLabelText('Add a word'), { target: { value: 'zz' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('button', { name: 'zaino' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText(/limit 500/)).toBeTruthy();
  });
});

describe('AddWord listen', () => {
  const withAudio = (norm: string) => async () => ({
    ...(await readyPreview(norm)()),
    audio: { word: 'a'.repeat(64), definition: 'b'.repeat(64) },
  });

  afterEach(() => vi.restoreAllMocks());

  it('plays a preview part by the key the preview gave it, and offers only parts with a key', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
    const speech = vi.fn(async () => new Blob(['mp3']));
    wrap({ me: async () => baseMe({}), preview: vi.fn(withAudio('mare')), speech } as Partial<Api>, <AddWord />);
    fireEvent.change(screen.getByLabelText('Add a word'), { target: { value: 'mare' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await screen.findByRole('button', { name: 'Save' });

    const listen = screen.getAllByRole('button', { name: 'Listen' });
    expect(listen.length).toBe(2);
    await act(async () => fireEvent.click(listen[0]!));
    expect(speech).toHaveBeenCalledWith('a'.repeat(64));
  });

  it('stops the preview clip when the sheet closes or the preview is tried again', async () => {
    const stop = vi.spyOn(ClipPlayer.prototype, 'stop');
    wrap({ me: async () => baseMe({}), preview: vi.fn(withAudio('mare')) } as Partial<Api>, <AddWord />);
    fireEvent.change(screen.getByLabelText('Add a word'), { target: { value: 'mare' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await screen.findByRole('button', { name: 'Save' });
    stop.mockClear();

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(stop).toHaveBeenCalledTimes(1);
    await screen.findByRole('button', { name: 'Save' });
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(stop).toHaveBeenCalledTimes(2);
  });

  it('offers no Listen without keys', async () => {
    wrap({ me: async () => baseMe({}), preview: vi.fn(readyPreview('mare')) } as Partial<Api>, <AddWord />);
    fireEvent.change(screen.getByLabelText('Add a word'), { target: { value: 'mare' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await screen.findByRole('button', { name: 'Save' });

    expect(screen.queryByRole('button', { name: 'Listen' })).toBeNull();
  });
});

describe('Stepper', () => {
  it('flushes a pending change when it unmounts within the pause', () => {
    vi.useFakeTimers();
    try {
      const onCommit = vi.fn();
      const view = render(
        <I18nProvider initial="en">
          <Stepper label="Interval" value={120} min={30} max={1440} format={(v) => `${v}`} onCommit={onCommit} />
        </I18nProvider>,
      );
      fireEvent.click(screen.getByRole('button', { name: 'Longer interval' }));
      expect(onCommit).not.toHaveBeenCalled();
      view.unmount();
      expect(onCommit).toHaveBeenCalledTimes(1);
      expect(onCommit).toHaveBeenCalledWith(150);
      vi.advanceTimersByTime(1000);
      expect(onCommit).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
