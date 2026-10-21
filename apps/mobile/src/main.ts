import { Capacitor, CapacitorHttp } from '@capacitor/core';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';
import { normalizeOrigin } from './origin.js';
import { mediaFileName, parseRange, presetRange } from './media.js';
import './style.css';
import './features.css';

type Json = Record<string, unknown>;
type PersonCamera = { camera_id: string; camera_name: string; persons_crossed: number; crossings_down: number; crossings_up: number };
type People = { persons_crossed: number; crossings_down: number; crossings_up: number; cameras: PersonCamera[] };
type LiveSession = { cameraId: string; status: string; playbackUrl: string; sessionId: string; viewerKey: string; error?: string };
type BinaryResult = { base64?: string; blob?: Blob; mime: string };

const byId = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const access = byId<HTMLElement>('access');
const app = byId<HTMLElement>('app');
const originInput = byId<HTMLInputElement>('origin');
const accessStatus = byId<HTMLElement>('access-status');
const appStatus = byId<HTMLElement>('app-status');
const viewer = byId<HTMLDialogElement>('viewer');
const viewerVideo = byId<HTMLVideoElement>('viewer-video');
const viewerLoading = byId<HTMLElement>('viewer-loading');
const viewerStatus = byId<HTMLElement>('viewer-status');
const viewerActions = byId<HTMLElement>('viewer-actions');
let origin = '';
let csrf = '';
let cameras: Json[] = [];
let events: Json[] = [];
let recordings: Json[] = [];
let previewCachePath = '';
let previewObjectUrl = '';
let mediaRequest = 0;
let recordingQueue: Json[] = [];
let recordingIndex = -1;
let liveSession: LiveSession | null = null;
let liveCameraId = '';
let heartbeatTimer: ReturnType<typeof setTimeout> | undefined;
let stopWhep: (() => void) | undefined;

try {
  origin = normalizeOrigin(localStorage.getItem('vigilay-origin') || import.meta.env.VITE_VIGILAY_ORIGIN || '');
  originInput.value = origin;
} catch { /* La persona configura el origen en el acceso. */ }

async function api<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await CapacitorHttp.request({
    url: `${origin}/api/v1${path}`, method, data,
    headers: {
      'Content-Type': 'application/json', Origin: origin,
      ...(csrf ? {'X-CSRF-Token': csrf} : {}),
    },
    connectTimeout: 12_000, readTimeout: 30_000, responseType: 'json',
    webFetchExtra: { credentials: 'include' },
  });
  if (response.status < 200 || response.status >= 300) {
    const detail = response.data && typeof response.data.detail === 'string' ? response.data.detail : 'No se pudo completar la solicitud.';
    throw new Error(detail);
  }
  return response.data as T;
}

function text(id: string, value: unknown) { byId(id).textContent = String(value ?? ''); }
function clear(element: HTMLElement) { while (element.firstChild) element.firstChild.remove(); }
function node<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', value = '') {
  const element = document.createElement(tag); element.className = className; element.textContent = value; return element;
}
function button(label: string, className: string, action: (button: HTMLButtonElement) => void | Promise<void>) {
  const element = node('button', className, label); element.type = 'button';
  element.addEventListener('click', () => void action(element)); return element;
}
function value(id: string) { return byId<HTMLInputElement | HTMLSelectElement>(id).value; }
function setValue(id: string, next: string) { byId<HTMLInputElement | HTMLSelectElement>(id).value = next; }
function eventLabel(value: unknown) {
  const labels: Record<string, string> = { person: 'Persona', face: 'Rostro', car: 'Automóvil', bicycle: 'Bicicleta', motorcycle: 'Motocicleta', bus: 'Bus', truck: 'Camión', dog: 'Perro', cat: 'Gato', package: 'Paquete' };
  const key = String(value || 'evento').toLowerCase();
  return labels[key] || key.replace(/_/g, ' ').replace(/^./, character => character.toUpperCase());
}
function localDate(seconds: unknown) {
  return new Date(Number(seconds || 0) * 1000).toLocaleString('es-PE', { dateStyle: 'short', timeStyle: 'short' });
}
function duration(seconds: unknown) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  return total >= 60 ? `${Math.floor(total / 60)} min ${total % 60} s` : `${total} s`;
}

function initializeRanges() {
  const range = presetRange('today');
  for (const prefix of ['events', 'recordings']) {
    setValue(`${prefix}-from`, range.from); setValue(`${prefix}-to`, range.to);
  }
}

function populateCameraSelects() {
  for (const id of ['events-camera', 'recordings-camera']) {
    const select = byId<HTMLSelectElement>(id); const previous = select.value; clear(select);
    const first = node('option', '', id === 'events-camera' ? 'Todas las cámaras' : 'Selecciona una cámara'); first.value = ''; select.append(first);
    for (const camera of cameras.filter(item => item.integration_type !== 'SIMULATOR')) {
      const option = node('option', '', String(camera.name || 'Cámara')); option.value = String(camera.id); select.append(option);
    }
    if ([...select.options].some(option => option.value === previous)) select.value = previous;
  }
  const recordingSelect = byId<HTMLSelectElement>('recordings-camera');
  if (!recordingSelect.value && recordingSelect.options.length > 1) recordingSelect.value = recordingSelect.options[1].value;
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

function renderCameras() {
  text('camera-total', `${cameras.length} cámara${cameras.length === 1 ? '' : 's'}`);
  text('online-total', cameras.filter(camera => camera.status === 'ONLINE').length);
  const list = byId('camera-list'); clear(list);
  if (!cameras.length) { list.className = 'stack empty-state'; list.textContent = 'No hay cámaras disponibles.'; return; }
  list.className = 'stack';
  for (const camera of cameras) {
    const online = camera.status === 'ONLINE'; const card = node('article', 'camera-card'); const preview = node('div', 'camera-preview', 'V');
    const status = node('span', `status ${online ? 'online' : ''}`, online ? 'En línea' : 'Sin conexión'); const detail = node('div', 'camera-info');
    detail.append(node('strong', '', String(camera.name || 'Cámara')), node('small', '', String(camera.integration_type || 'RTSP')), status);
    if (camera.integration_type !== 'SIMULATOR' && camera.enabled !== false) detail.append(button('Ver en vivo', 'card-button live-button', () => openLive(camera)));
    card.append(preview, detail); list.append(card);
  }
}

function renderEvents() {
  text('event-total', events.length); const list = byId('event-list'); clear(list);
  if (!events.length) { list.className = 'stack empty-state'; list.textContent = 'No hay eventos en el intervalo seleccionado.'; return; }
  list.className = 'stack';
  for (const item of events) {
    const card = node('article', 'event-card'); const heading = node('div', 'event-heading'); const icon = node('span', 'event-icon', '⚑'); const detail = node('div');
    const crossed = Number(item.persons_crossed || 0); const label = crossed ? `${crossed} persona${crossed === 1 ? '' : 's'} cruzaron` : eventLabel(item.label);
    detail.append(node('strong', '', label), node('small', '', `${String(item.camera_name || 'Cámara')} · ${localDate(item.start_time)}`)); heading.append(icon, detail); card.append(heading);
    if (item.clip_url) {
      const actions = node('div', 'card-actions');
      actions.append(
        button('▶ Ver clip', 'primary', () => openMedia(String(item.clip_url), `${eventLabel(item.label)} · ${String(item.camera_name || 'Cámara')}`)),
        button('↓ Descargar', 'secondary', target => downloadMedia(String(item.clip_url), mediaFileName(item, 'evento'), target)),
      ); card.append(actions);
    } else card.append(node('p', 'no-clip', 'Evento registrado sin clip de video.'));
    list.append(card);
  }
}

function renderRecordings() {
  text('recording-total', `${recordings.length} video${recordings.length === 1 ? '' : 's'}`); const list = byId('recording-list'); clear(list);
  if (!recordings.length) { list.className = 'stack empty-state'; list.textContent = 'No hay grabaciones en el intervalo seleccionado.'; return; }
  list.className = 'stack';
  for (const item of recordings) {
    const card = node('article', 'recording-card'); const detail = node('div');
    detail.append(node('strong', '', String(item.camera_name || 'Cámara')), node('small', '', localDate(item.start)), node('small', '', `${duration(item.duration)} · ${Number(item.objects || 0)} objetos · ${Number(item.motion || 0)} movimientos`));
    const actions = node('div', 'card-actions');
    actions.append(
      button('▶ Reproducir', 'primary', () => openRecording(item)),
      button('↓ Descargar', 'secondary', target => downloadMedia(String(item.clip_url), mediaFileName(item, 'grabacion'), target)),
    ); card.append(detail, actions); list.append(card);
  }
}

async function loadEvents(showStatus = false) {
  const status = byId('events-status'); if (showStatus) status.textContent = 'Buscando eventos…';
  try {
    const range = parseRange(value('events-from'), value('events-to'), 7_776_000);
    const cameraId = value('events-camera'); const cameraQuery = cameraId ? `&camera_id=${encodeURIComponent(cameraId)}` : '';
    const [nextEvents, people] = await Promise.all([
      api<Json[]>(`/media/events?limit=200&${range.query}${cameraQuery}`),
      api<People>(`/media/people-counts?${range.query}${cameraQuery}`),
    ]);
    events = nextEvents; renderEvents(); renderPeople(people);
    text('events-range-label', `${value('events-from').replace('T', ' ')} – ${value('events-to').replace('T', ' ')}`);
    status.textContent = showStatus ? `${events.length} evento${events.length === 1 ? '' : 's'} encontrado${events.length === 1 ? '' : 's'}.` : '';
  } catch (error) {
    events = []; renderEvents(); renderPeople({persons_crossed: 0, crossings_down: 0, crossings_up: 0, cameras: []}); status.textContent = (error as Error).message;
  }
}

async function loadRecordings(showStatus = false) {
  const status = byId('recordings-status'); const cameraId = value('recordings-camera'); recordings = []; renderRecordings();
  if (!cameraId) { status.textContent = 'Selecciona una cámara para consultar sus grabaciones.'; return; }
  if (showStatus) status.textContent = 'Consultando Vigilay Recorder…';
  try {
    const range = parseRange(value('recordings-from'), value('recordings-to'), 604_800);
    recordings = await api<Json[]>(`/media/recordings?camera_id=${encodeURIComponent(cameraId)}&${range.query}`); renderRecordings();
    status.textContent = showStatus ? `${recordings.length} grabación${recordings.length === 1 ? '' : 'es'} encontrada${recordings.length === 1 ? '' : 's'}.` : '';
  } catch (error) { status.textContent = (error as Error).message; }
}

async function load() {
  appStatus.textContent = 'Actualizando…';
  try {
    const [me, metrics, nextCameras] = await Promise.all([api<Json>('/me'), api<Json>('/dashboard'), api<Json[]>('/cameras')]);
    csrf = String(me.csrf_token || csrf); cameras = nextCameras; populateCameraSelects(); renderCameras();
    text('user-name', me.first_name || 'Mi espacio'); text('profile-name', me.first_name || 'Usuario'); text('profile-email', me.email); text('profile-role', me.role);
    text('avatar', String(me.first_name || 'V').slice(0, 1).toUpperCase()); text('online-total', metrics.cameras_online || 0);
    await Promise.all([loadEvents(), loadRecordings()]); appStatus.textContent = '';
  } catch (error) { appStatus.textContent = (error as Error).message; }
}

function responseMime(headers: Record<string, string>) {
  const entry = Object.entries(headers).find(([key]) => key.toLowerCase() === 'content-type'); return entry?.[1]?.split(';')[0] || 'video/mp4';
}
async function fetchMedia(path: string, asDownload = false): Promise<BinaryResult> {
  const url = new URL(path, origin); if (asDownload) url.searchParams.set('download', 'true');
  const response = await CapacitorHttp.request({
    url: url.toString(), method: 'GET', headers: { Origin: origin }, responseType: 'blob',
    connectTimeout: 15_000, readTimeout: 120_000, webFetchExtra: { credentials: 'include' },
  });
  if (response.status < 200 || response.status >= 300) throw new Error(`No se pudo obtener el video (${response.status}).`);
  if (response.data instanceof Blob) return { blob: response.data, mime: response.data.type || responseMime(response.headers) };
  if (typeof response.data !== 'string') throw new Error('La API no devolvió un archivo de video válido.');
  return { base64: response.data.replace(/^data:[^;]+;base64,/, ''), mime: responseMime(response.headers) };
}

function base64Blob(base64: string, mime: string) {
  const binary = atob(base64); const chunks: Uint8Array[] = [];
  for (let offset = 0; offset < binary.length; offset += 512 * 1024) {
    const slice = binary.slice(offset, offset + 512 * 1024); const bytes = new Uint8Array(slice.length);
    for (let index = 0; index < slice.length; index += 1) bytes[index] = slice.charCodeAt(index);
    chunks.push(bytes);
  }
  return new Blob(chunks, { type: mime });
}

async function clearPreview() {
  if (previewObjectUrl) { URL.revokeObjectURL(previewObjectUrl); previewObjectUrl = ''; }
  if (previewCachePath) { const path = previewCachePath; previewCachePath = ''; await Filesystem.deleteFile({ path, directory: Directory.Cache }).catch(() => {}); }
  viewerVideo.removeAttribute('src'); viewerVideo.srcObject = null; viewerVideo.load();
}

function showViewer(title: string, kicker: string) {
  text('viewer-title', title); text('viewer-kicker', kicker); viewerStatus.textContent = ''; viewerLoading.textContent = 'Preparando video…'; viewerLoading.hidden = false; viewerVideo.hidden = true; viewerActions.hidden = true;
  if (!viewer.open) viewer.showModal();
}

async function openMedia(path: string, title: string, queue?: Json[], index = -1) {
  if (!path) return; await stopLive(); const request = ++mediaRequest; showViewer(title, 'GRABACIÓN');
  recordingQueue = queue || []; recordingIndex = index;
  try {
    await clearPreview(); const binary = await fetchMedia(path); if (request !== mediaRequest) return;
    if (Capacitor.isNativePlatform() && binary.base64) {
      previewCachePath = `vigilay-preview-${Date.now()}.mp4`;
      const result = await Filesystem.writeFile({ path: previewCachePath, data: binary.base64, directory: Directory.Cache });
      viewerVideo.src = Capacitor.convertFileSrc(result.uri);
    } else {
      const blob = binary.blob || base64Blob(binary.base64 || '', binary.mime); previewObjectUrl = URL.createObjectURL(blob); viewerVideo.src = previewObjectUrl;
    }
    viewerVideo.hidden = false; viewerLoading.hidden = true; await viewerVideo.play().catch(() => { viewerStatus.textContent = 'Pulsa reproducir para iniciar el video.'; });
  } catch (error) { if (request === mediaRequest) { viewerLoading.textContent = (error as Error).message; viewerStatus.textContent = 'Comprueba que Vigilay Recorder esté conectado.'; } }
}

function openRecording(item: Json) {
  const queue = [...recordings].sort((left, right) => Number(left.start) - Number(right.start));
  const index = queue.findIndex(row => row.clip_url === item.clip_url);
  return openMedia(String(item.clip_url), `Grabación · ${String(item.camera_name || 'Cámara')}`, queue, index);
}

async function downloadMedia(path: string, filename: string, target: HTMLButtonElement) {
  const previous = target.textContent; target.disabled = true; target.textContent = 'Descargando…';
  try {
    const binary = await fetchMedia(path, true);
    if (Capacitor.isNativePlatform()) {
      if (!binary.base64) throw new Error('No se pudo preparar el archivo para guardarlo.');
      const permission = await Filesystem.checkPermissions();
      if (permission.publicStorage === 'prompt' || permission.publicStorage === 'prompt-with-rationale') await Filesystem.requestPermissions();
      const saved = await Filesystem.writeFile({ path: `Vigilay/${filename}`, data: binary.base64, directory: Directory.Documents, recursive: true });
      appStatus.textContent = `Video guardado en Documentos/Vigilay/${filename}`;
      if ((await Share.canShare()).value) await Share.share({ title: filename, files: [saved.uri], dialogTitle: 'Guardar o compartir video' });
    } else {
      const blob = binary.blob || base64Blob(binary.base64 || '', binary.mime); const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = filename; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  } catch (error) { appStatus.textContent = (error as Error).message; }
  finally { target.disabled = false; target.textContent = previous; }
}

function startWhep(playbackUrl: string) {
  let stopped = false; let attempts = 0; let retry: ReturnType<typeof setTimeout> | undefined; let cleanup = () => {};
  const release = (url: string) => { if (url) void fetch(url, { method: 'DELETE', keepalive: true }).catch(() => {}); };
  const reconnect = () => {
    if (stopped || retry) return; cleanup();
    if (attempts >= 8) { viewerLoading.textContent = 'No se pudo recibir el video en vivo.'; viewerStatus.textContent = 'Comprueba la conexión de la sede e inténtalo otra vez.'; return; }
    viewerStatus.textContent = 'Reconectando transmisión…'; const delay = Math.min(400 * 2 ** attempts++, 5000) + Math.random() * 200;
    retry = setTimeout(() => { retry = undefined; void connect(); }, delay);
  };
  const connect = async () => {
    if (stopped) return; viewerStatus.textContent = 'Conectando video seguro…';
    const peer = new RTCPeerConnection({ bundlePolicy: 'max-bundle' }); const stream = new MediaStream(); const abort = new AbortController();
    let disposed = false; let resource = ''; let frameCallback = 0; let lastFrame = performance.now(); let receivedFrame = false; let disconnected: ReturnType<typeof setTimeout> | undefined;
    const offerTimeout = setTimeout(() => abort.abort(), 8000);
    const watchdog = setInterval(() => { if (performance.now() - lastFrame > 15_000) reconnect(); }, 3000);
    cleanup = () => {
      if (disposed) return; disposed = true; abort.abort(); clearTimeout(offerTimeout); clearTimeout(disconnected); clearInterval(watchdog);
      if (frameCallback && typeof viewerVideo.cancelVideoFrameCallback === 'function') viewerVideo.cancelVideoFrameCallback(frameCallback);
      peer.close(); stream.getTracks().forEach(track => track.stop()); viewerVideo.srcObject = null; release(resource);
    };
    const frameArrived = () => {
      if (disposed) return; lastFrame = performance.now();
      if (!receivedFrame) { receivedFrame = true; attempts = 0; viewerLoading.hidden = true; viewerVideo.hidden = false; viewerStatus.textContent = 'En vivo'; }
      if (typeof viewerVideo.requestVideoFrameCallback === 'function') frameCallback = viewerVideo.requestVideoFrameCallback(frameArrived);
    };
    if (typeof viewerVideo.requestVideoFrameCallback === 'function') frameCallback = viewerVideo.requestVideoFrameCallback(frameArrived);
    else { viewerVideo.onplaying = frameArrived; clearInterval(watchdog); }
    peer.addTransceiver('video', { direction: 'recvonly' }); peer.addTransceiver('audio', { direction: 'recvonly' });
    peer.ontrack = ({ track }) => { if (disposed) return; stream.addTrack(track); viewerVideo.srcObject = stream; void viewerVideo.play().catch(() => { viewerStatus.textContent = 'Pulsa reproducir para iniciar el live.'; }); };
    peer.onconnectionstatechange = () => {
      if (disposed) return; if (peer.connectionState === 'failed') reconnect();
      if (peer.connectionState === 'disconnected' && !disconnected) disconnected = setTimeout(reconnect, 3000);
      if (peer.connectionState === 'connected') { clearTimeout(disconnected); disconnected = undefined; }
    };
    try {
      const offer = await peer.createOffer(); await peer.setLocalDescription(offer);
      const response = await fetch(playbackUrl, { method: 'POST', headers: {'content-type': 'application/sdp'}, body: offer.sdp, signal: abort.signal });
      const location = response.headers.get('location'); const created = location ? new URL(location, playbackUrl).toString() : '';
      if (disposed) { release(created); return; } resource = created;
      if (!response.ok) throw new Error('WHEP no disponible');
      await peer.setRemoteDescription({ type: 'answer', sdp: await response.text() }); clearTimeout(offerTimeout);
    } catch { if (!disposed && !stopped) reconnect(); }
  };
  void connect(); return () => { stopped = true; clearTimeout(retry); cleanup(); viewerVideo.onplaying = null; };
}

function scheduleHeartbeat() {
  clearTimeout(heartbeatTimer); if (!liveSession || !liveCameraId) return;
  heartbeatTimer = setTimeout(async () => {
    if (!liveSession) return;
    try {
      const state = await api<LiveSession>(`/cameras/${liveCameraId}/live/heartbeat`, 'POST', { session_id: liveSession.sessionId, viewer_key: liveSession.viewerKey });
      viewerStatus.textContent = state.status === 'live' ? 'En vivo' : `Estado: ${state.status}`; scheduleHeartbeat();
    } catch (error) { viewerStatus.textContent = (error as Error).message; }
  }, 12_000);
}

async function openLive(camera: Json) {
  await closeViewer(); liveCameraId = String(camera.id); showViewer(String(camera.name || 'Cámara'), 'EN VIVO');
  viewerVideo.muted = true; viewerActions.hidden = false; byId<HTMLButtonElement>('viewer-sound').textContent = 'Activar sonido';
  try {
    liveSession = await api<LiveSession>(`/cameras/${liveCameraId}/live/start`, 'POST');
    if (!liveSession.playbackUrl) throw new Error(liveSession.error || 'La transmisión no devolvió una dirección de reproducción.');
    stopWhep = startWhep(liveSession.playbackUrl); scheduleHeartbeat();
  } catch (error) { viewerLoading.textContent = (error as Error).message; viewerStatus.textContent = 'No se pudo iniciar el live.'; }
}

async function stopLive() {
  clearTimeout(heartbeatTimer); stopWhep?.(); stopWhep = undefined; const session = liveSession; const cameraId = liveCameraId; liveSession = null; liveCameraId = '';
  if (session && cameraId) await api(`/cameras/${cameraId}/live/stop`, 'POST', { session_id: session.sessionId, viewer_key: session.viewerKey }).catch(() => {});
}

async function closeViewer() {
  mediaRequest += 1; await stopLive(); await clearPreview(); recordingQueue = []; recordingIndex = -1;
  if (viewer.open) viewer.close();
}

byId<HTMLFormElement>('login').addEventListener('submit', async event => {
  event.preventDefault(); accessStatus.textContent = ''; const target = byId<HTMLButtonElement>('login-button'); target.disabled = true; target.textContent = 'Ingresando…';
  try {
    origin = normalizeOrigin(originInput.value); localStorage.setItem('vigilay-origin', origin);
    const result = await api<{csrf_token: string}>('/auth/login', 'POST', { identifier: value('identifier'), password: value('password') });
    csrf = result.csrf_token; access.hidden = true; app.hidden = false; await load();
  } catch (error) { accessStatus.textContent = (error as Error).message; }
  finally { target.disabled = false; target.innerHTML = 'Entrar a mi espacio <span>→</span>'; }
});

byId<HTMLFormElement>('events-filter').addEventListener('submit', event => { event.preventDefault(); void loadEvents(true); });
byId<HTMLFormElement>('recordings-filter').addEventListener('submit', event => { event.preventDefault(); void loadRecordings(true); });
for (const target of document.querySelectorAll<HTMLButtonElement>('[data-event-preset]')) target.addEventListener('click', () => {
  const range = presetRange(target.dataset.eventPreset as 'today' | 'yesterday' | 'seven'); setValue('events-from', range.from); setValue('events-to', range.to); void loadEvents(true);
});
for (const target of document.querySelectorAll<HTMLButtonElement>('[data-recording-preset]')) target.addEventListener('click', () => {
  const range = presetRange(target.dataset.recordingPreset as 'today' | 'yesterday' | 'seven'); setValue('recordings-from', range.from); setValue('recordings-to', range.to); void loadRecordings(true);
});
byId<HTMLSelectElement>('events-camera').addEventListener('change', () => void loadEvents(true));
byId<HTMLSelectElement>('recordings-camera').addEventListener('change', () => void loadRecordings(true));

for (const target of document.querySelectorAll<HTMLButtonElement>('[data-view]')) {
  target.addEventListener('click', () => {
    const selected = target.dataset.view;
    document.querySelectorAll<HTMLElement>('.view').forEach(view => view.hidden = view.id !== `${selected}-view`);
    document.querySelectorAll<HTMLButtonElement>('[data-view]').forEach(item => item.classList.toggle('active', item === target));
  });
}
byId('refresh').addEventListener('click', () => void load());
byId('viewer-close').addEventListener('click', () => void closeViewer());
viewer.addEventListener('cancel', event => { event.preventDefault(); void closeViewer(); });
viewer.addEventListener('click', event => { if (event.target === viewer) void closeViewer(); });
viewerVideo.addEventListener('ended', () => {
  if (recordingIndex < 0 || recordingIndex + 1 >= recordingQueue.length) return;
  recordingIndex += 1; const next = recordingQueue[recordingIndex]; void openMedia(String(next.clip_url), `Grabación · ${String(next.camera_name || 'Cámara')}`, recordingQueue, recordingIndex);
});
byId('viewer-sound').addEventListener('click', () => { viewerVideo.muted = !viewerVideo.muted; text('viewer-sound', viewerVideo.muted ? 'Activar sonido' : 'Silenciar'); });
byId('logout').addEventListener('click', async () => {
  await closeViewer(); try { await api('/auth/logout', 'POST'); } catch { /* La sesión local se cierra igualmente. */ }
  csrf = ''; app.hidden = true; access.hidden = false; byId<HTMLInputElement>('password').value = '';
});
window.addEventListener('pagehide', () => { void stopLive(); });

initializeRanges();
if (origin) {
  void api<Json>('/me').then(me => { csrf = String(me.csrf_token || ''); access.hidden = true; app.hidden = false; return load(); }).catch(() => {});
}
