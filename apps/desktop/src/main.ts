import { invoke } from '@tauri-apps/api/core';
import './style.css';
import './live.css';

type Row = {
  id: string;
  name: string;
  tenant_id?: string;
  site_id?: string;
  status?: string;
  integration_type?: string;
};
type User = { id: string; tenant_id?: string | null; role: string; first_name?: string };
type LoginResult = { connected: boolean; user: User };
type LiveResult = { playbackUrl: string; sessionId: string; viewerKey: string; status: string };
type RecorderState = { running?: boolean; site_id?: string | null; output_dir: string; retention_days?: number; min_free_gb?: number; detector?: string; confidence?: number; camera_count: number };
type ActiveLive = LiveResult & { cameraId: string; peer?: RTCPeerConnection; resource: string; heartbeat?: number };

let tenants: Row[] = [];
let sites: Row[] = [];
let busy = false;
let currentUser: User | null = null;
let activeLive: ActiveLive | null = null;

const byId = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const values = (form: HTMLFormElement) => Object.fromEntries(new FormData(form).entries());
const selected = () => ({ tenant_id: byId<HTMLSelectElement>('tenant').value, site_id: byId<HTMLSelectElement>('site').value });
const administrator = () => ['SUPER_ADMIN', 'CLIENT_ADMIN'].includes(currentUser?.role || '');

async function ensureVideoAgent() {
  const badge = byId('agent-badge');
  try {
    await invoke('ensure_stream_agent');
    badge.textContent = 'Agente de video: automático';
    badge.classList.add('running');
  } catch (error) {
    badge.textContent = `Agente de video: ${String(error)}`;
    badge.classList.remove('running');
  }
}

function option(select: HTMLSelectElement, value: string, label: string) {
  const item = document.createElement('option');
  item.value = value;
  item.textContent = label;
  select.append(item);
}

async function operation(label: string, task: () => Promise<unknown>) {
  if (busy) return;
  busy = true;
  const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>('button'))
    .map(button => ({ button, wasDisabled: button.disabled }));
  buttons.forEach(({ button }) => button.disabled = true);
  byId('status').textContent = `${label}…`;
  try {
    const result = await task();
    byId('result').textContent = JSON.stringify(result, null, 2);
    byId('status').textContent = `${label}: completado.`;
    return result;
  } catch (error) {
    byId('status').textContent = String(error);
    throw error;
  } finally {
    busy = false;
    buttons.forEach(({ button, wasDisabled }) => button.disabled = wasDisabled);
  }
}

function showRoleFeatures() {
  document.querySelectorAll<HTMLElement>('[data-admin-only]').forEach(element => {
    element.hidden = !administrator();
  });
}

function renderSites() {
  const select = byId<HTMLSelectElement>('site');
  const current = select.value;
  select.replaceChildren();
  option(select, '', 'Selecciona una sede');
  sites
    .filter(row => row.tenant_id === byId<HTMLSelectElement>('tenant').value)
    .forEach(row => option(select, row.id, row.name));
  select.value = Array.from(select.options).some(item => item.value === current) ? current : '';
}

function renderCatalog() {
  const select = byId<HTMLSelectElement>('tenant');
  const current = select.value;
  select.replaceChildren();
  option(select, '', 'Selecciona una empresa');
  tenants.forEach(row => option(select, row.id, row.name));
  select.value = tenants.some(row => row.id === current) ? current : '';
  renderSites();
}

function updateScopeBadge() {
  const tenant = byId<HTMLSelectElement>('tenant').selectedOptions[0]?.textContent;
  const site = byId<HTMLSelectElement>('site').selectedOptions[0]?.textContent;
  byId('scope-badge').textContent = tenant && site ? `${tenant} · ${site}` : 'Selecciona empresa y sede';
}

async function catalog() {
  const data = await invoke<{ tenants: Row[]; sites: Row[] }>('catalog');
  tenants = data.tenants;
  sites = data.sites;
  renderCatalog();
  return data;
}

function chooseInitialScope(user: User) {
  const tenant = byId<HTMLSelectElement>('tenant');
  tenant.value = user.tenant_id && tenants.some(row => row.id === user.tenant_id)
    ? user.tenant_id
    : tenants[0]?.id || '';
  renderSites();
  const site = byId<HTMLSelectElement>('site');
  site.value = sites.find(row => row.tenant_id === tenant.value)?.id || '';
  updateScopeBadge();
}

function renderRecorder(state: RecorderState) {
  const badge = byId('recorder-badge');
  badge.textContent = `${state.running ? 'Grabando' : 'Grabador detenido'} · ${state.camera_count} cámara(s)`;
  badge.classList.toggle('running', Boolean(state.running));
  const form = byId<HTMLFormElement>('recorder-form');
  byId<HTMLInputElement>('output-dir').value = state.output_dir || '';
  if (state.retention_days !== undefined) (form.elements.namedItem('retention_days') as HTMLInputElement).value = String(state.retention_days);
  if (state.min_free_gb !== undefined) (form.elements.namedItem('min_free_gb') as HTMLInputElement).value = String(state.min_free_gb);
  if (state.detector) (form.elements.namedItem('detector') as HTMLSelectElement).value = state.detector;
  if (state.confidence !== undefined) (form.elements.namedItem('confidence') as HTMLInputElement).value = String(state.confidence);
}

async function loadRecorder() {
  const state = await invoke<RecorderState>('recorder_status');
  renderRecorder(state);
  return state;
}

function liveState(message: string, running = false) {
  const badge = byId('live-status');
  badge.textContent = message;
  badge.classList.toggle('running', running);
}

function cleanupPeer(live: ActiveLive) {
  live.peer?.close();
  live.peer = undefined;
  const video = byId<HTMLVideoElement>('live-video');
  const media = video.srcObject as MediaStream | null;
  media?.getTracks().forEach(track => track.stop());
  video.srcObject = null;
  if (live.resource) {
    void fetch(live.resource, { method: 'DELETE', keepalive: true }).catch(() => {});
    live.resource = '';
  }
}

const pause = (milliseconds: number) => new Promise(resolve => window.setTimeout(resolve, milliseconds));

async function connectWhep(live: ActiveLive) {
  const delays = [0, 400, 800, 1600, 3200, 5000, 5000, 5000];
  let lastError: unknown = new Error('No llegó video');
  for (const delay of delays) {
    if (activeLive !== live) return;
    if (delay) await pause(delay);
    if (activeLive !== live) return;
    cleanupPeer(live);
    liveState(delay ? 'Reconectando…' : 'Conectando…');
    const peer = new RTCPeerConnection({ bundlePolicy: 'max-bundle' });
    live.peer = peer;
    const media = new MediaStream();
    const video = byId<HTMLVideoElement>('live-video');
    peer.addTransceiver('video', { direction: 'recvonly' });
    peer.addTransceiver('audio', { direction: 'recvonly' });
    peer.ontrack = ({ track }) => {
      if (activeLive !== live) return;
      media.addTrack(track);
      video.srcObject = media;
      void video.play().catch(() => liveState('Pulsa reproducir para iniciar'));
    };
    video.onplaying = () => liveState('En vivo', true);
    peer.onconnectionstatechange = () => {
      if (activeLive === live && peer.connectionState === 'failed') liveState('Reconectando…');
    };
    try {
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      const response = await fetch(live.playbackUrl, {
        method: 'POST',
        headers: { 'content-type': 'application/sdp' },
        body: offer.sdp,
        signal: AbortSignal.timeout(8000),
      });
      const location = response.headers.get('location');
      live.resource = location ? new URL(location, live.playbackUrl).toString() : '';
      if (!response.ok) throw new Error('El servicio WebRTC todavía no está listo');
      await peer.setRemoteDescription({ type: 'answer', sdp: await response.text() });
      return;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

async function closeLive(hide = true) {
  const live = activeLive;
  activeLive = null;
  if (live) {
    if (live.heartbeat) window.clearInterval(live.heartbeat);
    cleanupPeer(live);
    await invoke('stop_live', {
      cameraId: live.cameraId,
      sessionId: live.sessionId,
      viewerKey: live.viewerKey,
    }).catch(() => {});
  }
  if (hide) byId('live-section').hidden = true;
}

async function openLive(camera: Row) {
  await closeLive();
  byId('live-section').hidden = false;
  byId('live-title').textContent = camera.name;
  byId('live-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
  liveState('Solicitando transmisión…');
  try {
    const result = await invoke<LiveResult>('start_live', { cameraId: camera.id });
    const live: ActiveLive = { ...result, cameraId: camera.id, resource: '' };
    activeLive = live;
    live.heartbeat = window.setInterval(() => {
      if (activeLive !== live) return;
      void invoke<LiveResult>('heartbeat_live', {
        cameraId: live.cameraId,
        sessionId: live.sessionId,
        viewerKey: live.viewerKey,
      }).then(state => {
        if (['error', 'stopped'].includes(state.status)) {
          liveState('La transmisión se detuvo');
          void closeLive(false);
        }
      }).catch(error => {
        liveState(String(error));
        void closeLive(false);
      });
    }, 10000);
    await connectWhep(live);
  } catch (error) {
    await closeLive(false);
    liveState(`No se pudo abrir el video: ${String(error)}`);
  }
}

async function loadCameras() {
  const scope = selected();
  if (!scope.tenant_id || !scope.site_id) throw new Error('Selecciona una empresa y una sede.');
  const rows = await invoke<Row[]>('cameras', {
    tenantId: scope.tenant_id,
    siteId: scope.site_id,
  });
  const list = byId('camera-list');
  list.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement('li');
    empty.textContent = 'No tienes cámaras asignadas en esta sede.';
    list.append(empty);
  }
  rows.forEach(row => {
    const item = document.createElement('li');
    const details = document.createElement('span');
    const name = document.createElement('strong');
    const status = document.createElement('small');
    const button = document.createElement('button');
    name.textContent = row.name;
    status.textContent = row.status === 'ONLINE' ? 'En línea' : row.status || 'Estado desconocido';
    details.append(name, status);
    button.type = 'button';
    button.textContent = '▶ Ver en vivo';
    button.disabled = row.status !== 'ONLINE' || row.integration_type === 'SIMULATOR';
    button.onclick = () => void openLive(row);
    item.append(details, button);
    list.append(item);
  });
  return rows;
}

byId('tenant').addEventListener('change', () => {
  renderSites();
  const site = byId<HTMLSelectElement>('site');
  site.value = sites.find(row => row.tenant_id === selected().tenant_id)?.id || '';
  updateScopeBadge();
  void closeLive();
  if (site.value) void loadCameras().catch(error => byId('status').textContent = String(error));
});

byId('site').addEventListener('change', () => {
  updateScopeBadge();
  void closeLive();
  if (selected().site_id) void loadCameras().catch(error => byId('status').textContent = String(error));
});

byId<HTMLFormElement>('login-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget as HTMLFormElement;
  void operation('Inicio de sesión', async () => {
    const result = await invoke<LoginResult>('login', { settings: values(form) });
    currentUser = result.user;
    (form.elements.namedItem('password') as HTMLInputElement).value = '';
    byId('admin').hidden = false;
    byId('login-section').hidden = true;
    showRoleFeatures();
    await catalog();
    chooseInitialScope(result.user);
    if (selected().site_id) await loadCameras();
    if (administrator()) await loadRecorder();
    return { connected: true, role: result.user.role };
  }).catch(() => {});
});

byId<HTMLFormElement>('tenant-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget as HTMLFormElement;
  void operation('Crear empresa', async () => {
    const result = await invoke<Row>('create_tenant', { data: values(form) });
    await catalog();
    byId<HTMLSelectElement>('tenant').value = result.id;
    renderSites();
    form.reset();
    return result;
  }).catch(() => {});
});

byId<HTMLFormElement>('site-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget as HTMLFormElement;
  const tenant_id = selected().tenant_id;
  if (!tenant_id) { byId('status').textContent = 'Selecciona primero una empresa.'; return; }
  void operation('Crear sede', async () => {
    const result = await invoke<Row>('create_site', { data: { ...values(form), tenant_id } });
    await catalog();
    byId<HTMLSelectElement>('tenant').value = tenant_id;
    renderSites();
    byId<HTMLSelectElement>('site').value = result.id;
    updateScopeBadge();
    form.reset();
    return result;
  }).catch(() => {});
});

byId('refresh-cameras').onclick = () => void operation('Actualizar cámaras', loadCameras).catch(() => {});
byId('close-live').onclick = () => void closeLive();
byId('sync-recording-cameras').onclick = () => void operation('Sincronizar accesos', async () => {
  const scope = selected();
  if (!scope.site_id) throw new Error('Selecciona una empresa y una sede.');
  const result = await invoke('sync_recording_cameras', { siteId: scope.site_id });
  await Promise.all([loadCameras(), loadRecorder()]);
  return result;
}).catch(() => {});

byId<HTMLFormElement>('camera-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget as HTMLFormElement;
  const scope = selected();
  if (!scope.tenant_id || !scope.site_id) { byId('status').textContent = 'Selecciona una empresa y una sede.'; return; }
  void operation('Agregar cámara', async () => {
    const recorder = await loadRecorder();
    if (recorder.running) throw new Error('Detén la grabación antes de agregar otra cámara.');
    const fields = values(form);
    const result = await invoke<Row>('create_camera', { data: { ...fields, ...scope } });
    await invoke('register_recording_camera', { data: { site_id: scope.site_id, id: result.id, name: String(fields.name), source: String(fields.rtsp_url), fps: 15 } });
    form.reset();
    await Promise.all([loadCameras(), loadRecorder()]);
    return result;
  }).catch(() => {});
});

byId('choose-output').onclick = () => void operation('Elegir carpeta', async () => {
  const path = await invoke<string | null>('choose_recording_directory');
  if (path) byId<HTMLInputElement>('output-dir').value = path;
  return { output_dir: path };
}).catch(() => {});

byId<HTMLFormElement>('recorder-form').addEventListener('submit', event => {
  event.preventDefault();
  const fields = values(event.currentTarget as HTMLFormElement);
  void operation('Guardar grabador', async () => {
    const result = await invoke('save_recorder_settings', { data: { output_dir: fields.output_dir, retention_days: Number(fields.retention_days), min_free_gb: Number(fields.min_free_gb), detector: fields.detector, confidence: Number(fields.confidence) } });
    await loadRecorder();
    return result;
  }).catch(() => {});
});

byId('start-recorder').onclick = () => void operation('Iniciar grabación', async () => {
  const siteId = selected().site_id;
  if (!siteId) throw new Error('Selecciona la sede que grabará.');
  const result = await invoke('start_recorder', { siteId });
  await loadRecorder();
  return result;
}).catch(() => {});
byId('stop-recorder').onclick = () => void operation('Detener grabación', async () => { const result = await invoke('stop_recorder'); await loadRecorder(); return result; }).catch(() => {});
byId('open-recordings').onclick = () => void operation('Abrir grabaciones', () => invoke('open_recordings')).catch(() => {});
byId('open-web').onclick = () => void operation('Abrir Vigilay', () => invoke('open_web')).catch(() => {});
byId('logout').onclick = () => void operation('Cerrar sesión', async () => {
  await closeLive();
  const result = await invoke('logout');
  currentUser = null;
  byId('admin').hidden = true;
  byId('login-section').hidden = false;
  byId('scope-badge').textContent = 'Sesión no iniciada';
  byId('camera-list').replaceChildren();
  return result;
}).catch(() => {});

window.addEventListener('pagehide', () => { void closeLive(); });
void ensureVideoAgent();
