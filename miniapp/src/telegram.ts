// Thin, defensive wrapper around window.Telegram.WebApp. Every call is guarded because
// older clients lack many methods, and the app must also run in a plain browser.

export type Scheme = 'light' | 'dark';
export type HapticKind = 'light' | 'medium' | 'success' | 'warning' | 'error' | 'select';

interface Inset {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

interface WebAppLike {
  initData?: string;
  initDataUnsafe?: { user?: { language_code?: string } };
  colorScheme?: Scheme;
  isVersionAtLeast?: (v: string) => boolean;
  ready?: () => void;
  expand?: () => void;
  disableVerticalSwipes?: () => void;
  setHeaderColor?: (c: string) => void;
  setBackgroundColor?: (c: string) => void;
  requestWriteAccess?: (cb: (allowed: boolean) => void) => void;
  setBottomBarColor?: (c: string) => void;
  onEvent?: (name: string, cb: () => void) => void;
  safeAreaInset?: Inset;
  contentSafeAreaInset?: Inset;
  BackButton?: {
    show?: () => void;
    hide?: () => void;
    onClick?: (cb: () => void) => void;
    offClick?: (cb: () => void) => void;
  };
  HapticFeedback?: {
    impactOccurred?: (s: 'light' | 'medium') => void;
    notificationOccurred?: (s: 'success' | 'warning' | 'error') => void;
    selectionChanged?: () => void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: WebAppLike };
  }
}

function webApp(): WebAppLike | undefined {
  return typeof window === 'undefined' ? undefined : window.Telegram?.WebApp;
}

function guard(fn: () => void): void {
  try {
    fn();
  } catch {
    /* an unsupported call must never break the app */
  }
}

function atLeast(version: string): boolean {
  const app = webApp();
  if (!app) return false;
  try {
    return app.isVersionAtLeast ? app.isVersionAtLeast(version) : false;
  } catch {
    return false;
  }
}

/** Init data for the Authorization header. The dev fallback is removed from production builds. */
export function getInitData(): string {
  const real = webApp()?.initData ?? '';
  if (real) return real;
  if (import.meta.env.DEV) return import.meta.env.VITE_DEV_INIT_DATA ?? '';
  return '';
}

export function telegramLanguage(): string | undefined {
  return webApp()?.initDataUnsafe?.user?.language_code;
}

export function currentScheme(): Scheme {
  const fromTelegram = webApp()?.colorScheme;
  if (fromTelegram === 'dark' || fromTelegram === 'light') return fromTelegram;
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'dark';
  return 'light';
}

function applySafeArea(): void {
  const app = webApp();
  const root = document.documentElement.style;
  const sum = (side: keyof Inset) => (app?.safeAreaInset?.[side] ?? 0) + (app?.contentSafeAreaInset?.[side] ?? 0);
  for (const side of ['top', 'bottom', 'left', 'right'] as const) {
    root.setProperty(`--tg-safe-${side}`, `${sum(side)}px`);
  }
}

function applyScheme(): void {
  document.documentElement.dataset.scheme = currentScheme();
  const app = webApp();
  if (!app) return;
  // Match Telegram's own chrome to the theme. Colors are read from the CSS tokens.
  const style = getComputedStyle(document.documentElement);
  const color = (name: string) => {
    const v = style.getPropertyValue(name).trim();
    return /^#[0-9a-f]{6}$/i.test(v) ? v : null;
  };
  const ground = color('--color-ground');
  const surface = color('--color-surface');
  if (ground && atLeast('6.1')) {
    guard(() => app.setHeaderColor?.(ground));
    guard(() => app.setBackgroundColor?.(ground));
  }
  if (surface && atLeast('7.10')) guard(() => app.setBottomBarColor?.(surface));
}

/** Call once at startup. */
export function initTelegram(): void {
  const app = webApp();
  document.documentElement.dataset.theme = 'sticker';
  applyScheme();
  applySafeArea();
  if (!app) return;
  guard(() => app.ready?.());
  guard(() => app.expand?.());
  if (atLeast('7.7')) guard(() => app.disableVerticalSwipes?.());
  guard(() => app.onEvent?.('themeChanged', applyScheme));
  guard(() => app.onEvent?.('safeAreaChanged', applySafeArea));
  guard(() => app.onEvent?.('contentSafeAreaChanged', applySafeArea));
}

export function haptic(kind: HapticKind): void {
  const h = webApp()?.HapticFeedback;
  if (!h || !atLeast('6.1')) return;
  guard(() => {
    if (kind === 'light' || kind === 'medium') h.impactOccurred?.(kind);
    else if (kind === 'select') h.selectionChanged?.();
    else h.notificationOccurred?.(kind);
  });
}

// BackButton stack: the most recent owner (a sheet, then the study screen) handles the press.
const backStack: Array<() => void> = [];
let backBound = false;

function onBackPressed(): void {
  const top = backStack[backStack.length - 1];
  if (top) top();
}

function syncBack(): void {
  const bb = webApp()?.BackButton;
  if (!bb || !atLeast('6.1')) return;
  if (backStack.length > 0) {
    if (!backBound) {
      guard(() => bb.onClick?.(onBackPressed));
      backBound = true;
    }
    guard(() => bb.show?.());
  } else {
    guard(() => bb.hide?.());
    if (backBound) {
      guard(() => bb.offClick?.(onBackPressed));
      backBound = false;
    }
  }
}

/** Show the Telegram BackButton and route presses to `handler`. Returns the release function. */
export function pushBackHandler(handler: () => void): () => void {
  const entry = () => handler();
  backStack.push(entry);
  syncBack();
  return () => {
    const i = backStack.indexOf(entry);
    if (i >= 0) backStack.splice(i, 1);
    syncBack();
  };
}

/** Whether this client can ask the user to let the bot write to them (Bot API 6.9). */
export function canRequestWriteAccess(): boolean {
  return atLeast('6.9') && typeof webApp()?.requestWriteAccess === 'function';
}

/** Ask Telegram to let the bot message the user. Resolves false when unsupported or refused. */
export function requestWriteAccess(): Promise<boolean> {
  return new Promise((resolve) => {
    const app = webApp();
    if (!canRequestWriteAccess() || !app?.requestWriteAccess) {
      resolve(false);
      return;
    }
    try {
      app.requestWriteAccess((allowed) => resolve(Boolean(allowed)));
    } catch {
      resolve(false);
    }
  });
}
