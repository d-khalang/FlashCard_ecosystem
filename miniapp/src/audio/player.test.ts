import { describe, expect, it, vi } from 'vitest';
import { ClipPlayer, MAX_CLIPS, SILENT_CLIP } from './player';

function setup() {
  const sources: string[] = [];
  const element = {
    src: '',
    paused: true,
    play: vi.fn(async function (this: { src: string }) {
      sources.push(element.src);
    }),
    pause: vi.fn(),
  };
  let n = 0;
  const revokeUrl = vi.fn();
  const player = new ClipPlayer({ element, createUrl: () => `blob:${++n}`, revokeUrl });
  return { player, element, sources, revokeUrl };
}

const blob = new Blob(['x']);

describe('ClipPlayer', () => {
  it('unlocks playback during the tap, then plays the downloaded clip', async () => {
    const { player, sources } = setup();
    await player.play('a', async () => blob);
    expect(sources).toEqual([SILENT_CLIP, 'blob:1']);
  });

  it('replays from memory without a request', async () => {
    const { player, sources } = setup();
    const load = vi.fn(async () => blob);
    await player.play('a', load);
    await player.play('a', load);
    expect(load).toHaveBeenCalledTimes(1);
    expect(sources.at(-1)).toBe('blob:1');
  });

  it('lets the newest tap win over a slower download', async () => {
    const { player, sources } = setup();
    let finishFirst: (b: Blob) => void = () => undefined;
    const first = player.play('a', () => new Promise<Blob>((r) => (finishFirst = r)));
    await player.play('b', async () => blob);
    finishFirst(blob);
    await first;
    expect(sources.at(-1)).toBe('blob:1');
  });

  it('stays quiet about a download that fails after a newer tap', async () => {
    const { player } = setup();
    let failFirst: (e: Error) => void = () => undefined;
    const first = player.play('a', () => new Promise<Blob>((_, reject) => (failFirst = reject)));
    await player.play('b', async () => blob);
    failFirst(new Error('boom'));
    await expect(first).resolves.toBeUndefined();
  });

  it('stays quiet when a newer tap aborts playback that was starting', async () => {
    const { player, element } = setup();
    await player.play('a', async () => blob);
    let abort: (e: Error) => void = () => undefined;
    element.play.mockImplementationOnce(() => new Promise<void>((_, reject) => (abort = reject)));
    const first = player.play('a', async () => blob);
    await player.play('b', async () => blob);
    abort(new DOMException('interrupted', 'AbortError'));
    await expect(first).resolves.toBeUndefined();
  });

  it('still reports a failed play of the latest tap', async () => {
    const { player, element } = setup();
    await player.play('a', async () => blob);
    element.play.mockImplementationOnce(() => Promise.reject(new Error('blocked')));
    await expect(player.play('a', async () => blob)).rejects.toThrow('blocked');
  });

  it('stop drops a tap still downloading, and silences what is playing', async () => {
    const { player, element, sources } = setup();
    let finish: (b: Blob) => void = () => undefined;
    const first = player.play('a', () => new Promise<Blob>((r) => (finish = r)));
    element.paused = false;
    element.pause.mockClear();

    player.stop();
    finish(blob);
    await first;

    expect(element.pause).toHaveBeenCalledTimes(1);
    expect(sources).toEqual([SILENT_CLIP]);
  });

  it('counts a clip downloaded twice as just used', async () => {
    const { player, revokeUrl } = setup();
    let finish: (b: Blob) => void = () => undefined;
    const slow = player.play('old', () => new Promise<Blob>((r) => (finish = r)));
    await player.play('old', async () => blob);
    for (let i = 1; i < MAX_CLIPS; i += 1) await player.play(`c${i}`, async () => blob);
    finish(blob);
    await slow;
    await player.play('new', async () => blob);
    expect(revokeUrl).toHaveBeenCalledTimes(1);
    expect(revokeUrl).not.toHaveBeenCalledWith('blob:1');
  });

  it('keeps a limited number of clips and frees the oldest', async () => {
    const { player, revokeUrl } = setup();
    for (let i = 0; i <= MAX_CLIPS; i += 1) await player.play(`c${i}`, async () => blob);
    expect(revokeUrl).toHaveBeenCalledTimes(1);
    expect(revokeUrl).toHaveBeenCalledWith('blob:1');
  });

  it('passes a failed download on to the caller and can try again', async () => {
    const { player, sources } = setup();
    await expect(player.play('a', async () => Promise.reject(new Error('boom')))).rejects.toThrow('boom');
    await player.play('a', async () => blob);
    expect(sources.at(-1)).toBe('blob:1');
  });
});
