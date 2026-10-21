import { CapacitorHttp } from '@capacitor/core';
import { normalizeOrigin } from './origin.js';
import './style.css';

type Json = Record<string, unknown>;
type PersonCamera = { camera_id: string; camera_name: string; persons_crossed: number; crossings_down: number; crossings_up: number };
type People = { persons_crossed: number; crossings_down: number; crossings_up: number; cameras: PersonCamera[] };

const byId = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const access = byId<HTMLElement>('access');
const app = byId<HTMLElement>('app');
const originInput = byId<HTMLInputElement>('origin');
const accessStatus = byId<HTMLElement>('access-status');
const appStatus = byId<HTMLElement>('app-status');
let origin = '';
let csrf = '';

try {
  origin = normalizeOrigin(localStorage.getItem('vigilay-origin') || import.meta.env.VITE_VIGILAY_ORIGIN || '');
  originInput.value = origin;
} catch { /* La persona configura el origen en el acceso. */ }

async function api<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await CapacitorHttp.request({
    url: `${origin}/api/v1${path}`,
    method,
    data,
    headers: {
      'Content-Type': 'application/json', Origin: origin,
      ...(csrf ? {'X-CSRF-Token': csrf} : {}),
    },
    connectTimeout: 12_000, readTimeout: 20_000, responseType: 'json',
    webFetchExtra: { credentials: 'include' },
  });
  if (response.status < 200 || response.status >= 300) {
    const detail = response.data && typeof response.data.detail === 'string' ? response.data.detail : 'No se pudo completar la solicitud.';
    throw new Error(detail);
  }
  return response.data as T;
}

function todayRange() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return `after=${Math.floor(start.getTime() / 1000)}&before=${Math.floor(now.getTime() / 1000)}`;
}

function text(id: string, value: unknown) { byId(id).textContent = String(value ?? ''); }
function clear(element: HTMLElement) { while (element.firstChild) element.firstChild.remove(); }
function node<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', value = '') {
  const element = document.createElement(tag); element.className = className; element.textContent = value; return element;
}

function renderPeople(data: People) {
  text('people-total', data.persons_crossed); text('crossings-down', data.crossings_down); text('crossings-up', data.crossings_up);
  const list = byId('people-cameras'); clear(list);
  if (!data.cameras.length) { list.className = 'stack empty-state'; list.textContent = 'Aún no hay cruces registrados.'; return; }
  list.className = 'stack';
  for (const item of data.cameras) {
    const card = node('article', 'list-card'); const icon = node('span', 'camera-icon', '◉'); const detail = node('div');
    detail.append(node('strong', '', item.camera_name), node('small', '', `${item.crossings_down} ↓  ·  ${item.crossings_up} ↑`));
    card.append(icon, detail, node('b', 'count-bubble', String(item.persons_crossed))); list.append(card);
  }
}

function renderCameras(cameras: Json[]) {
  text('camera-total', `${cameras.length} cámara${cameras.length === 1 ? '' : 's'}`);
  text('online-total', cameras.filter(camera => camera.status === 'ONLINE').length);
  const list = byId('camera-list'); clear(list);
  if (!cameras.length) { list.className = 'stack empty-state'; list.textContent = 'No hay cámaras disponibles.'; return; }
  list.className = 'stack';
  for (const camera of cameras) {
    const online = camera.status === 'ONLINE'; const card = node('article', 'camera-card'); const preview = node('div', 'camera-preview', 'V');
    const status = node('span', `status ${online ? 'online' : ''}`, online ? 'En línea' : 'Sin conexión'); const detail = node('div', 'camera-info');
    detail.append(node('strong', '', String(camera.name || 'Cámara')), node('small', '', String(camera.integration_type || 'RTSP')), status);
    card.append(preview, detail); list.append(card);
  }
}

function renderEvents(events: Json[]) {
  text('event-total', events.length); const list = byId('event-list'); clear(list);
  if (!events.length) { list.className = 'stack empty-state'; list.textContent = 'No hay eventos disponibles.'; return; }
  list.className = 'stack';
  for (const event of events) {
    const card = node('article', 'list-card event-row'); const icon = node('span', 'event-icon', '⚑'); const detail = node('div');
    const when = new Date(Number(event.start_time || 0) * 1000).toLocaleTimeString('es-PE', {hour: '2-digit', minute: '2-digit'}); const crossed = Number(event.persons_crossed || 0);
    detail.append(node('strong', '', crossed ? `${crossed} persona${crossed === 1 ? '' : 's'} cruzaron` : 'Persona detectada'), node('small', '', `${String(event.camera_name || 'Cámara')} · ${when}`));
    card.append(icon, detail); list.append(card);
  }
}

async function load() {
  appStatus.textContent = 'Actualizando…';
  try {
    const range = todayRange();
    const [me, metrics, cameras] = await Promise.all([
      api<Json>('/me'), api<Json>('/dashboard'), api<Json[]>('/cameras'),
    ]);
    let recorderOffline = false;
    const [people, events] = await Promise.all([
      api<People>(`/media/people-counts?${range}`).catch(() => { recorderOffline = true; return {persons_crossed: 0, crossings_down: 0, crossings_up: 0, cameras: []}; }),
      api<Json[]>(`/media/events?limit=50&${range}`).catch(() => { recorderOffline = true; return []; }),
    ]);
    csrf = String(me.csrf_token || csrf); text('user-name', me.first_name || 'Mi espacio');
    text('profile-name', me.first_name || 'Usuario'); text('profile-email', me.email); text('profile-role', me.role);
    text('avatar', String(me.first_name || 'V').slice(0, 1).toUpperCase()); text('online-total', metrics.cameras_online || 0);
    renderPeople(people); renderCameras(cameras); renderEvents(events);
    appStatus.textContent = recorderOffline ? 'Vigilay Recorder está desconectado; se muestran los datos de cámaras disponibles.' : '';
  } catch (error) { appStatus.textContent = (error as Error).message; }
}

byId<HTMLFormElement>('login').addEventListener('submit', async event => {
  event.preventDefault(); accessStatus.textContent = ''; const button = byId<HTMLButtonElement>('login-button'); button.disabled = true; button.textContent = 'Ingresando…';
  try {
    origin = normalizeOrigin(originInput.value); localStorage.setItem('vigilay-origin', origin);
    const result = await api<{csrf_token: string; user: Json}>('/auth/login', 'POST', {identifier: byId<HTMLInputElement>('identifier').value, password: byId<HTMLInputElement>('password').value});
    csrf = result.csrf_token; access.hidden = true; app.hidden = false; await load();
  } catch (error) { accessStatus.textContent = (error as Error).message; }
  finally { button.disabled = false; button.innerHTML = 'Entrar a mi espacio <span>→</span>'; }
});

for (const button of document.querySelectorAll<HTMLButtonElement>('[data-view]')) {
  button.addEventListener('click', () => {
    const selected = button.dataset.view;
    document.querySelectorAll<HTMLElement>('.view').forEach(view => view.hidden = view.id !== `${selected}-view`);
    document.querySelectorAll<HTMLButtonElement>('[data-view]').forEach(item => item.classList.toggle('active', item === button));
  });
}
byId('refresh').addEventListener('click', () => void load());
byId('logout').addEventListener('click', async () => {
  try { await api('/auth/logout', 'POST'); } catch { /* La sesión local se cierra igualmente. */ }
  csrf = ''; app.hidden = true; access.hidden = false; byId<HTMLInputElement>('password').value = '';
});
