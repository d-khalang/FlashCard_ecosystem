/**
 * Plays card audio through one element. Clips are kept in memory so that a replay costs no request:
 * apart from words, the server generates each clip anew, and most of them are never played again
 * once the card has changed. The newest tap wins.
 */

/** A moment of silent MP3, in the format edge-tts sends (24 kHz, 48 kbps). Playing it during the tap lets the real clip start after its download on iOS. */
export const SILENT_CLIP =
  'data:audio/mpeg;base64,//NkxAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//NkxAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//NkxAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//NkxAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

/** Clips kept: a whole card (5 parts) and the one before it. */
export const MAX_CLIPS = 10;

export interface ClipElement {
  src: string;
  readonly paused: boolean;
  play(): Promise<void>;
  pause(): void;
}

export interface PlayerEnv {
  element: ClipElement;
  createUrl: (blob: Blob) => string;
  revokeUrl: (url: string) => void;
}

export class ClipPlayer {
  private readonly clips = new Map<string, string>();
  private latest = 0;

  constructor(private readonly env: PlayerEnv) {}

  /**
   * Call during the tap. Resolves when playback started, or when a newer tap or `stop` replaced this
   * tap: what happens to an abandoned tap, failures included, no longer concerns anyone.
   */
  async play(id: string, load: () => Promise<Blob>): Promise<void> {
    const tap = ++this.latest;
    const { element } = this.env;
    element.pause();

    try {
      let url = this.clips.get(id);
      if (url === undefined) {
        // Not awaited: blocked or failed, the real clip still gets its chance below.
        element.src = SILENT_CLIP;
        element.play().catch(() => undefined);
        url = this.remember(id, await load());
      } else {
        this.markUsed(id, url);
      }
      if (tap !== this.latest) return;
      element.pause();
      element.src = url;
      await element.play();
    } catch (e) {
      if (tap === this.latest) throw e;
    }
  }

  /** Silence, and drop a tap still downloading: its card is no longer on screen. */
  stop(): void {
    this.latest += 1;
    if (!this.env.element.paused) this.env.element.pause();
  }

  /** Most recently used goes last, so it is dropped last. */
  private markUsed(id: string, url: string): void {
    this.clips.delete(id);
    this.clips.set(id, url);
  }

  private remember(id: string, blob: Blob): string {
    const existing = this.clips.get(id);
    if (existing !== undefined) {
      this.markUsed(id, existing);
      return existing;
    }
    const url = this.env.createUrl(blob);
    this.clips.set(id, url);
    if (this.clips.size > MAX_CLIPS) {
      const [oldestId, oldestUrl] = this.clips.entries().next().value as [string, string];
      this.clips.delete(oldestId);
      this.env.revokeUrl(oldestUrl);
    }
    return url;
  }
}

export function createBrowserPlayer(): ClipPlayer {
  return new ClipPlayer({
    element: new Audio(),
    createUrl: (blob) => URL.createObjectURL(blob),
    revokeUrl: (url) => URL.revokeObjectURL(url),
  });
}
