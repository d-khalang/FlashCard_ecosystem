import { createRoot } from 'react-dom/client';
import './theme/sticker.css';
import './styles/base.css';
import './styles/components.css';
import './styles/screens.css';
import { App } from './App';
import { I18nProvider } from './i18n';
import { initTelegram } from './telegram';

async function bootstrap(): Promise<void> {
  initTelegram();

  // Dev only: `?mock` in the URL serves a fake API. The whole block is removed from production builds.
  let fetchImpl: typeof fetch | undefined;
  if (import.meta.env.DEV && new URLSearchParams(location.search).has('mock')) {
    const { createMockFetch } = await import('./dev/mockFetch');
    fetchImpl = createMockFetch(new URLSearchParams(location.search));
  }

  createRoot(document.getElementById('root')!).render(
    <I18nProvider>
      <App fetchImpl={fetchImpl} />
    </I18nProvider>,
  );
}

void bootstrap();
