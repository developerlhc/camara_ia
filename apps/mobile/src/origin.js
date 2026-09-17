export function normalizeOrigin(value) {
  const url = new URL(String(value).trim());
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash ||
      (url.pathname !== '/' && url.pathname !== '') || url.hostname === 'localhost' ||
      url.hostname === '127.0.0.1' || url.hostname === '[::1]') {
    throw new Error('Introduce sólo el origen HTTPS de Vigilay, sin ruta, usuario ni parámetros.');
  }
  return url.origin;
}
export const allowedPages = ['/cameras', '/recordings', '/events', '/dashboard'];
export function pageUrl(origin, page) {
  if (!allowedPages.includes(page)) throw new Error('Sección no permitida.');
  return normalizeOrigin(origin) + page;
}
