export type Row = { id: string; [key: string]: unknown };
export type Me = { id: string; tenant_id: string | null; email: string; first_name: string; role: string; permissions: string[]; csrf_token: string };

let csrf = '';
export function setCsrf(value: string) { csrf = value; }

export async function api<T = Row[]>(path: string, method = 'GET', data?: unknown, options: { keepalive?: boolean } = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method, credentials: 'same-origin', keepalive: options.keepalive,
    headers: { 'content-type': 'application/json', 'x-csrf-token': csrf },
    body: data === undefined ? undefined : JSON.stringify(data)
  });
  if (response.status === 401 && path !== '/auth/login') {
    location.assign('/login');
    throw new Error('Tu sesión ha expirado');
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'No se pudo completar la solicitud' }));
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Revisa los datos ingresados');
  }
  return response.status === 204 ? undefined as T : response.json();
}
