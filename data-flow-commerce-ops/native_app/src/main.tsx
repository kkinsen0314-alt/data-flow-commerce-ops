import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '@/App';
import { shouldUseHashRouter } from '@/utils/url';
import { cleanupLegacyPwaArtifacts } from '@/utils/legacyPwaCleanup';
import './styles.css';

if (typeof window !== 'undefined') {
  window.__MINICLAW_HASH_ROUTER__ = shouldUseHashRouter();
  document.addEventListener('gesturestart', (event) => event.preventDefault());
  document.addEventListener('gesturechange', (event) => event.preventDefault());
  void cleanupLegacyPwaArtifacts();
}

const root = document.getElementById('root');

if (!root) {
  throw new Error('Data Flow root element is missing.');
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
