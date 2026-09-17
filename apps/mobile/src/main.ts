import { Capacitor } from '@capacitor/core';
import { InAppBrowser, DefaultWebViewOptions, DefaultSystemBrowserOptions } from '@capacitor/inappbrowser';
import { normalizeOrigin, pageUrl } from './origin.js';
import './style.css';

const origin = document.querySelector<HTMLInputElement>('#origin')!;
const status = document.querySelector<HTMLElement>('#status')!;
const system = document.querySelector<HTMLInputElement>('#system')!;
let configured = '';
let opening = false;
try {
  configured = normalizeOrigin(localStorage.getItem('vigilay-origin') || import.meta.env.VITE_VIGILAY_ORIGIN || '');
  origin.value = configured;
} catch { /* Configure the public URL before logging in. */ }
document.querySelector('#connection')!.addEventListener('submit', (event) => {
  event.preventDefault();
  try {
    configured = normalizeOrigin(origin.value);
    localStorage.setItem('vigilay-origin', configured);
    origin.value = configured;
    status.textContent = 'Conexión guardada: ' + configured;
  } catch (error) { status.textContent = String((error as Error).message); }
});
for (const button of document.querySelectorAll<HTMLButtonElement>('[data-page]')) {
  button.addEventListener('click', async () => {
    if (opening) return;
    try {
      const url = pageUrl(configured, button.dataset.page!);
      opening = true;
      status.textContent = 'Abriendo ' + configured;
      if (!Capacitor.isNativePlatform()) {
        window.location.assign(url);
      } else if (system.checked) {
        await InAppBrowser.openInSystemBrowser({ url, options: DefaultSystemBrowserOptions });
      } else {
        await InAppBrowser.openInWebView({
          url,
          options: {
            ...DefaultWebViewOptions,
            showURL: true, showToolbar: true, showNavigationButtons: true,
            clearCache: false, clearSessionCache: false,
            mediaPlaybackRequiresUserAction: false,
            closeButtonText: 'Volver a Vigilay',
            android: { ...DefaultWebViewOptions.android, hardwareBack: true, pauseMedia: true },
            iOS: { ...DefaultWebViewOptions.iOS, allowInLineMediaPlayback: true },
          },
        });
      }
    } catch (error) {
      status.textContent = (error as Error).message || 'No se pudo abrir Vigilay.';
    } finally { opening = false; }
  });
}
