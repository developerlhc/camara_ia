import { env } from '$env/dynamic/private';
import type { RequestHandler } from './$types';

const proxy: RequestHandler = async ({ request, params, url, getClientAddress }) => {
  if (!params.path.startsWith('v1/')) return new Response(null, { status: 404 });
  const headers = new Headers();
  if (env.INTERNAL_PROXY_SECRET) {
    headers.set('x-vigilay-proxy-key', env.INTERNAL_PROXY_SECRET);
    headers.set('x-vigilay-client-ip', getClientAddress());
  }
  for (const key of ['content-type', 'cookie', 'x-csrf-token', 'user-agent']) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  // The browser talks only to this same-origin proxy. Normalize localhost and
  // 127.0.0.1 to the canonical origin expected by the API's CSRF policy.
  headers.set('origin', env.ORIGIN || 'http://localhost:3000');
  try {
    const upstream = await fetch(`${env.API_INTERNAL_URL || 'http://127.0.0.1:8000'}/api/${params.path}${url.search}`, {
      method: request.method,
      headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.text(),
      redirect: 'manual',
      signal: AbortSignal.timeout(30000)
    });
    const responseHeaders = new Headers(upstream.headers);
    responseHeaders.delete('content-encoding');
    responseHeaders.delete('content-length');
    responseHeaders.set('cache-control', 'no-store');
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json({ detail: 'La API de Vigilay no está disponible. Comprueba los servicios.' }, { status: 503 });
  }
};

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
