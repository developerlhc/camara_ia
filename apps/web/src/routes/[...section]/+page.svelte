<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { page } from '$app/state';
  import { api, setCsrf, type Me, type Row } from '$lib/api';
  import WhepPlayer from '$lib/WhepPlayer.svelte';
  import LiveTile from '$lib/LiveTile.svelte';

  type CameraPermissionRow = Row & { user_id: string; can_view: boolean; can_configure: boolean };

  const titles: Record<string, string> = { dashboard: 'Resumen general', 'admin/customers': 'Clientes', 'admin/sites': 'Sedes', 'admin/users': 'Usuarios', cameras: 'Cámaras', events: 'Eventos de IA', recordings: 'Grabaciones', 'admin/audit': 'Auditoría', 'admin/system': 'Estado del sistema', profile: 'Mi perfil' };
  const endpoints: Record<string, string> = { 'admin/customers': '/tenants', 'admin/sites': '/sites', 'admin/users': '/users', cameras: '/cameras', 'admin/audit': '/audit' };
  let section = $derived(page.params.section || 'dashboard');
  let cameraId = $derived(section.startsWith('cameras/') ? section.split('/')[1] : '');
  let title = $derived(cameraId ? 'Detalle de cámara' : titles[section] || 'Página no encontrada');
  let user = $state<Me | null>(null); let loading = $state(true); let busy = $state(false);
  let error = $state(''); let notice = $state(''); let records = $state<Row[]>([]);
  let tenants = $state<Row[]>([]); let sites = $state<Row[]>([]);
  let metrics = $state<Record<string, number>>({}); let health = $state<Record<string, string>>({});
  let cloudflare = $state<Record<string, unknown>>({});
  let cloudflareAccountId = $state(''); let cloudflareApiToken = $state('');
  let camera = $state<Row | null>(null); let capabilities = $state<Row[]>([]); let settings = $state<Row[]>([]); let commands = $state<Row[]>([]);
  let showForm = $state(false); let editing = $state(''); let search = $state('');
  let filterTenant = $state(''); let filterStatus = $state(''); let filterIntegration = $state('');
  let cameraTenant = $state(''); let cameraSite = $state('');
  let camerasLoading = $state(false); let recordsRequest = 0;
  let pageNumber = $state(1); let pageSize = $state(10); let totalRecords = $state(0); let totalPages = $state(1);
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  let name = $state(''); let tenantId = $state(''); let siteId = $state(''); let address = $state('');
  let email = $state(''); let username = $state(''); let password = $state(''); let firstName = $state(''); let lastName = $state(''); let role = $state('VIEWER'); let status = $state('ACTIVE');
  let integration = $state('RTSP'); let rtspUrl = $state(''); let sensitivity = $state(50);
  let cameraBrand = $state('EZVIZ'); let cameraModel = $state(''); let cameraHost = $state('');
  let cameraUsername = $state(''); let cameraPassword = $state(''); let cameraDeviceId = $state('');
  let cameraPermissions = $state<CameraPermissionRow[]>([]);
  let currentPassword = $state(''); let newPassword = $state('');
  let liveOpen = $state(false); let liveStatus = $state('stopped');
  let liveCameraId = $state(''); let liveCameraName = $state('');
  let liveUrl = $state(''); let liveSessionId = $state(''); let liveViewerKey = $state('');
  let frigateCameras = $state<Row[]>([]); let frigateName = $state('');
  let frigateEvents = $state<Row[]>([]); let recordings = $state<Row[]>([]);
  let frigateCameraId = $state(''); let mediaUrl = $state(''); let mediaTitle = $state(''); let mediaKind = $state('video');
  let recordingTenant = $state(''); let recordingSite = $state(''); let recordingPage = $state(1); let recordingPageSize = $state(10);
  let recordingAfter = $state(''); let recordingBefore = $state('');
  let recordingsLoading = $state(false); let recordingsError = $state(''); let recordingsRequest = 0;
  let eventsTenant = $state(''); let eventsPage = $state(1); let eventsPageSize = $state(12);
  let eventsCameraId = $state(''); let eventsAfter = $state(''); let eventsBefore = $state('');
  let mediaQueue = $state<Row[]>([]); let mediaIndex = $state(-1);
  let liveTimer: ReturnType<typeof setTimeout> | undefined;
  let realtimeSocket: WebSocket | undefined; let realtimeRetry: ReturnType<typeof setTimeout> | undefined;
  let realtimeStopping = false;
  const commandWaiters = new Map<string, (command: Row) => void>();
  let filtered = $derived(records);
  let recordingCameras = $derived(records.filter(row => row.frigate_camera_name && (!recordingTenant || row.tenant_id === recordingTenant) && (!recordingSite || row.site_id === recordingSite)));
  let recordingPages = $derived(Math.max(1, Math.ceil(recordings.length / recordingPageSize)));
  let pagedRecordings = $derived(recordings.slice((recordingPage - 1) * recordingPageSize, recordingPage * recordingPageSize));
  let eventsCameras = $derived(records.filter(row => row.frigate_camera_name && (!eventsTenant || row.tenant_id === eventsTenant)));
  let filteredEvents = $derived(frigateEvents.filter(item => (!eventsTenant || item.tenant_id === eventsTenant) && (!eventsCameraId || item.camera_id === eventsCameraId)));
  let eventsPages = $derived(Math.max(1, Math.ceil(filteredEvents.length / eventsPageSize)));
  let pagedEvents = $derived(filteredEvents.slice((eventsPage - 1) * eventsPageSize, eventsPage * eventsPageSize));
  const pad2 = (n: number) => String(n).padStart(2, '0');
  const toLocalInput = (date: Date) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
  function setEventsRange(daysAgoStart: number, daysAgoEnd: number) {
    const end = new Date(); end.setHours(23, 59, 59, 0); end.setDate(end.getDate() - daysAgoEnd);
    const start = new Date(); start.setHours(0, 0, 0, 0); start.setDate(start.getDate() - daysAgoStart);
    eventsAfter = toLocalInput(start); eventsBefore = toLocalInput(end);
    void action(refresh, 'Eventos actualizados.');
  }
  function clearEventsRange() { eventsAfter = ''; eventsBefore = ''; void action(refresh, 'Eventos actualizados.'); }
  function mediaFileName(item: Row, prefix: string) {
    const camera = String(item.camera_name || 'camara').replace(/[^a-zA-Z0-9-]+/g, '_');
    const label = String(item.label || '').replace(/[^a-zA-Z0-9-]+/g, '_');
    const seconds = Number(item.start_time ?? item.start ?? 0);
    const when = (seconds ? new Date(seconds * 1000) : new Date()).toISOString().replace(/[:.]/g, '-');
    return `${prefix}-${camera}${label ? '-' + label : ''}-${when}.mp4`;
  }
  const display = (value: unknown) => value === null || value === undefined ? '—' : String(value);
  const nameOf = (rows: Row[], id: unknown) => display(rows.find(r => r.id === id)?.name || '—');
  const can = (key: string) => user?.permissions.includes(key) || false;
  const stateLabel = (value: unknown) => ({ ACTIVE: 'Activo', SUSPENDED: 'Suspendido', DISABLED: 'Deshabilitado', ONLINE: 'En línea', OFFLINE: 'Sin conexión', UNVERIFIED: 'Sin verificar', SYNCED: 'Sincronizado', DRIFTED: 'Configuración diferente', PENDING: 'Pendiente', RUNNING: 'Ejecutando', SUCCEEDED: 'Completado', FAILED: 'Falló', ERROR: 'Error' }[String(value)] || display(value));
  const roleLabel = (value: unknown) => ({ SUPER_ADMIN: 'Superadministrador', CLIENT_ADMIN: 'Administrador de cliente', OPERATOR: 'Operador', VIEWER: 'Observador' }[String(value)] || display(value));
  const eventLabels: Record<string, string> = { person: 'Persona', face: 'Rostro', car: 'Automóvil', bicycle: 'Bicicleta', motorcycle: 'Motocicleta', bus: 'Bus', truck: 'Camión', boat: 'Bote', train: 'Tren', dog: 'Perro', cat: 'Gato', bird: 'Ave', horse: 'Caballo', sheep: 'Oveja', cow: 'Vaca', bear: 'Oso', deer: 'Venado', squirrel: 'Ardilla', raccoon: 'Mapache', fox: 'Zorro', rabbit: 'Conejo', package: 'Paquete', license_plate: 'Placa vehicular', backpack: 'Mochila', umbrella: 'Paraguas', handbag: 'Bolso', suitcase: 'Maleta', skateboard: 'Patineta' };
  const eventLabel = (value: unknown) => {
    const key = String(value ?? '').toLowerCase().trim();
    if (!key) return display(value);
    return eventLabels[key] || key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
  };

  async function loadRecords() {
    const requestId = ++recordsRequest;
    const isCameras = section === 'cameras';
    if (isCameras) camerasLoading = true;
    const params = new URLSearchParams({ paged: 'true', page: String(pageNumber), page_size: String(isCameras ? 4 : pageSize) });
    if (search.trim()) params.set('q', search.trim());
    if (isCameras ? cameraTenant : filterTenant) params.set('tenant_id', isCameras ? cameraTenant : filterTenant);
    if (isCameras && cameraSite) params.set('site_id', cameraSite);
    if (filterStatus) params.set('status', filterStatus);
    if (filterIntegration && section === 'cameras') params.set('integration_type', filterIntegration);
    try {
      const result = await api<{items: Row[]; total: number; pages: number}>(`${endpoints[section]}?${params}`);
      if (requestId !== recordsRequest) return;
      records = result.items; totalRecords = result.total; totalPages = Math.max(1, result.pages);
      if (pageNumber > totalPages) { pageNumber = totalPages; await loadRecords(); }
    } finally { if (requestId === recordsRequest) camerasLoading = false; }
  }

  function chooseCameraScope(companyChanged = false) {
    if (companyChanged || !sites.some(row => row.id === cameraSite && row.tenant_id === cameraTenant)) {
      cameraSite = sites.find(row => row.tenant_id === cameraTenant)?.id || '';
    }
    try { localStorage.setItem(`vigilay-scope:${user?.id}`, JSON.stringify({tenant: cameraTenant, site: cameraSite})); } catch { /* Private browsing. */ }
    applyFilters();
  }

  function applyFilters() { pageNumber = 1; void refresh().catch(e => error = e.message); }
  function scheduleSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilters, 300);
  }

  function realtimeTarget() { return liveCameraId || cameraId; }
  function subscribeRealtime() {
    const target = realtimeTarget();
    if (!target || realtimeSocket?.readyState !== WebSocket.OPEN) return;
    realtimeSocket.send(JSON.stringify({
      type: 'subscribe', cameraId: target,
      sessionId: liveOpen && liveCameraId === target ? liveSessionId : '',
      viewerKey: liveOpen && liveCameraId === target ? liveViewerKey : ''
    }));
  }
  function applyRealtimeCommand(command: Row) {
    if (!['SUCCEEDED', 'FAILED', 'TIMEOUT', 'CANCELLED'].includes(String(command.status))) return;
    commandWaiters.get(command.id)?.(command);
  }
  function connectRealtime(target = realtimeTarget()) {
    if (!target || typeof WebSocket === 'undefined') return;
    realtimeStopping = false;
    if (realtimeSocket?.readyState === WebSocket.OPEN) { subscribeRealtime(); return; }
    if (realtimeSocket?.readyState === WebSocket.CONNECTING) return;
    clearTimeout(realtimeRetry);
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${location.host}/api/v1/realtime`);
    realtimeSocket = socket;
    socket.onopen = subscribeRealtime;
    socket.onmessage = (event) => {
      try {
        const update = JSON.parse(String(event.data));
        if (update.type !== 'snapshot') return;
        if (update.camera) {
          if (camera?.id === update.camera.id) camera = {...camera, ...update.camera};
          records = records.map(row => row.id === update.camera.id ? {...row, ...update.camera} : row);
        }
        if (Array.isArray(update.commands)) {
          commands = update.commands;
          update.commands.forEach(applyRealtimeCommand);
        }
        if (update.live?.sessionId === liveSessionId) {
          if (['error', 'stopped'].includes(update.live.status)) liveStatus = update.live.status;
          if (update.live.error) error = update.live.error;
        }
      } catch { /* Ignore malformed frames and keep the last valid state. */ }
    };
    socket.onclose = () => {
      if (realtimeSocket === socket) realtimeSocket = undefined;
      if (!realtimeStopping && realtimeTarget()) {
        realtimeRetry = setTimeout(() => connectRealtime(), 1000);
        if (liveOpen) scheduleLiveHeartbeat();
      }
    };
  }
  function disconnectRealtime() {
    realtimeStopping = true; clearTimeout(realtimeRetry);
    realtimeSocket?.close(); realtimeSocket = undefined;
  }
  async function waitForCommand(commandId: string, targetId: string, timeoutMs: number) {
    return new Promise<Row>((resolve, reject) => {
      let checking = false;
      const finish = (command: Row) => {
        clearTimeout(timeout); clearInterval(fallback); commandWaiters.delete(commandId);
        if (command.status === 'SUCCEEDED') resolve(command);
        else reject(new Error(display(command.error || 'El comando no pudo completarse.')));
      };
      const timeout = setTimeout(() => {
        clearInterval(fallback); commandWaiters.delete(commandId);
        reject(new Error('El agente local no confirmó el comando a tiempo.'));
      }, timeoutMs);
      const fallback = setInterval(async () => {
        if (realtimeSocket?.readyState === WebSocket.OPEN || checking) return;
        checking = true;
        try {
          const history = await api<Row[]>(`/cameras/${targetId}/commands`);
          const result = history.find(command => command.id === commandId);
          if (result && ['SUCCEEDED', 'FAILED', 'TIMEOUT', 'CANCELLED'].includes(String(result.status))) finish(result);
        } catch { /* A reconnect or the timeout will provide the final result. */ }
        finally { checking = false; }
      }, 1000);
      commandWaiters.set(commandId, finish);
      connectRealtime(targetId);
      subscribeRealtime();
    });
  }

  async function refresh() {
    error = '';
    if (cameraId) {
      camera = await api<Row>(`/cameras/${cameraId}`);
      if (can('cameras.configure')) await loadFrigateCatalog(display(camera.site_id));
      frigateName = display(camera.frigate_camera_name || '');
      capabilities = await api(`/cameras/${cameraId}/capabilities`);
      if (can('cameras.configure')) {
        settings = await api(`/cameras/${cameraId}/settings`);
        commands = await api(`/cameras/${cameraId}/commands`);
      }
      if (can('cameras.manage')) cameraPermissions = await api<CameraPermissionRow[]>(`/cameras/${cameraId}/permissions`);
    } else if (section === 'dashboard') {
      [metrics, records] = await Promise.all([api<Record<string, number>>('/dashboard'), api('/cameras')]);
      // An offline recording gateway must not block camera controls.
      void api<Row[]>('/frigate/events?limit=6').then(rows => { if (section === 'dashboard') frigateEvents = rows; }).catch(() => {});
    } else if (section === 'events') {
      const eventsParams = new URLSearchParams({ limit: '200' });
      if (eventsAfter) eventsParams.set('after', String(Math.floor(new Date(eventsAfter).getTime() / 1000)));
      if (eventsBefore) eventsParams.set('before', String(Math.floor(new Date(eventsBefore).getTime() / 1000)));
      [records, frigateEvents] = await Promise.all([api('/cameras'), api(`/frigate/events?${eventsParams}`)]);
      eventsPage = 1;
    } else if (section === 'recordings') {
      records = await api('/cameras');
      if (!recordingTenant && user?.tenant_id) recordingTenant = user.tenant_id;
      const mapped = records.filter(row => row.frigate_camera_name && (!recordingTenant || row.tenant_id === recordingTenant) && (!recordingSite || row.site_id === recordingSite));
      if (!frigateCameraId && mapped.length) frigateCameraId = display(mapped[0].id);
      await loadFrigateRecordings();
    } else if (section === 'admin/system') {
      health = await api<Record<string, string>>('/system/health');
      if (user?.role === 'SUPER_ADMIN') cloudflare = await api('/admin/integrations/cloudflare');
    }
    else if (endpoints[section]) await loadRecords();
  }
  let initialized = $state(false); let bootstrapFailed = $state(false);
  onMount(() => {
    const stopOnExit = () => { if (liveOpen) void closeLive(); };
    window.addEventListener('pagehide', stopOnExit);
    void (async () => {
      try {
        user = await api<Me>('/me'); setCsrf(user.csrf_token);
        [tenants, sites] = await Promise.all([api('/tenants'), api('/sites')]);
        tenantId = user.tenant_id || tenants[0]?.id || '';
        let saved: {tenant?: string; site?: string} = {};
        try { saved = JSON.parse(localStorage.getItem(`vigilay-scope:${user.id}`) || '{}') || {}; } catch { /* Use allowed defaults. */ }
        cameraTenant = user.tenant_id || (tenants.some(row => row.id === saved.tenant) ? saved.tenant! : tenants[0]?.id || '');
        cameraSite = sites.find(row => row.id === saved.site && row.tenant_id === cameraTenant)?.id || sites.find(row => row.tenant_id === cameraTenant)?.id || '';
        recordingTenant = cameraTenant; recordingSite = cameraSite;
        recordingBefore = toLocalInput(new Date()); recordingAfter = toLocalInput(new Date(Date.now() - 86400000));
      } catch(e) { error = (e as Error).message; loading = false; bootstrapFailed = true; }
      initialized = true;
    })();
    return () => { disconnectRealtime(); clearTimeout(searchTimer); window.removeEventListener('pagehide', stopOnExit); stopOnExit(); };
  });
  // Client-side navigation (no full page reload): re-run the section's data load
  // whenever the URL section changes, instead of only once at mount.
  $effect(() => {
    const currentSection = section;
    if (!initialized || bootstrapFailed) return;
    loading = true;
    untrack(() => { void closeLive(); void refresh().catch(e => error = e.message).finally(() => { loading = false; }); });
  });
  $effect(() => {
    const target = cameraId;
    if (!initialized || bootstrapFailed) return;
    if (target) connectRealtime(target); else disconnectRealtime();
  });

  async function loadFrigateCatalog(targetSite: string) {
    frigateCameras = targetSite
      ? await api<Row[]>(`/frigate/cameras?site_id=${encodeURIComponent(targetSite)}`).catch(() => [])
      : [];
  }

  async function action(work: () => Promise<unknown>, message: string) {
    busy = true; error = ''; notice = '';
    try { await work(); notice = message; if (work !== refresh && work !== loadFrigateRecordings) await refresh(); }
    catch(e) { error = (e as Error).message; } finally { busy = false; }
  }
  async function probeCamera() {
    busy = true; error = ''; notice = 'Comprobando la conexión con la cámara…';
    try {
      const queued = await api<{id: string}>(`/cameras/${cameraId}/probe`, 'POST');
      await waitForCommand(queued.id, cameraId, 30000);
      await refresh();
      notice = 'Conexión exitosa. La cámara está en línea.';
    } catch(e) { notice = ''; error = (e as Error).message; }
    finally { busy = false; }
  }
  async function openLive(targetId = cameraId, targetName = display(camera?.name)) {
    if (liveOpen) return;
    liveCameraId = targetId; liveCameraName = targetName;
    liveOpen = true; liveStatus = 'connecting'; error = '';
    try {
      const result = await api<Record<string, string>>(`/cameras/${targetId}/live/start`, 'POST');
      if (!liveOpen || liveCameraId !== targetId) {
        await api(`/cameras/${targetId}/live/stop`, 'POST', {session_id: result.sessionId, viewer_key: result.viewerKey});
        return;
      }
      liveUrl = result.playbackUrl; liveSessionId = result.sessionId;
      liveViewerKey = result.viewerKey; liveStatus = result.status;
      connectRealtime(targetId); subscribeRealtime();
      scheduleLiveHeartbeat();
    } catch (e) { liveStatus = 'error'; error = (e as Error).message; }
  }
  function scheduleLiveHeartbeat() {
    clearTimeout(liveTimer);
    if (!liveOpen || !liveSessionId || ['error', 'stopped'].includes(liveStatus)) return;
    liveTimer = setTimeout(async () => {
      try {
        if (realtimeSocket?.readyState === WebSocket.OPEN) { scheduleLiveHeartbeat(); return; }
        const state = await api<Record<string, string>>(`/cameras/${liveCameraId}/live/heartbeat`, 'POST', {session_id: liveSessionId, viewer_key: liveViewerKey});
        if (['error', 'stopped'].includes(state.status)) liveStatus = state.status;
        scheduleLiveHeartbeat();
      } catch (e) { liveStatus = 'error'; error = (e as Error).message; }
    }, 12000);
  }
  async function closeLive() {
    const sessionId = liveSessionId; const viewerKey = liveViewerKey; const targetId = liveCameraId;
    clearTimeout(liveTimer); liveOpen = false; liveStatus = 'stopped'; liveUrl = ''; liveSessionId = ''; liveViewerKey = '';
    if (sessionId && viewerKey && targetId) {
      await api(`/cameras/${targetId}/live/stop`, 'POST', {session_id: sessionId, viewer_key: viewerKey}, {keepalive: true}).catch(() => {});
    }
    liveCameraId = ''; liveCameraName = '';
    if (cameraId) subscribeRealtime(); else { realtimeSocket?.close(); realtimeSocket = undefined; }
  }
  async function loadFrigateRecordings() {
    const requestId = ++recordingsRequest;
    recordings = []; recordingPage = 1; recordingsError = ''; mediaUrl = ''; mediaQueue = []; mediaIndex = -1;
    recordingsLoading = false;
    if (!frigateCameraId) return;
    const before = Math.floor(new Date(recordingBefore).getTime() / 1000);
    const after = Math.floor(new Date(recordingAfter).getTime() / 1000);
    if (!Number.isFinite(after) || !Number.isFinite(before) || before <= after || before - after > 604800) {
      recordingsError = 'Selecciona fecha y hora de inicio y fin: máximo 7 días.'; return;
    }
    recordingsLoading = true;
    try {
      const rows = await api<Row[]>(`/frigate/recordings?camera_id=${encodeURIComponent(frigateCameraId)}&after=${after}&before=${before}`);
      if (requestId === recordingsRequest) recordings = rows;
    } catch (e) { if (requestId === recordingsRequest) recordingsError = (e as Error).message; }
    finally { if (requestId === recordingsRequest) recordingsLoading = false; }
  }
  function selectRecordingScope() {
    recordingPage = 1; recordings = [];
    if (frigateCameraId && !recordingCameras.some(row => row.id === frigateCameraId)) frigateCameraId = '';
    if (!frigateCameraId && recordingCameras.length) frigateCameraId = display(recordingCameras[0].id);
    void loadFrigateRecordings();
  }
  function openRecording(item: Row) {
    mediaQueue = [...recordings].sort((a, b) => Number(a.start) - Number(b.start)); mediaIndex = mediaQueue.findIndex(row => row.clip_url === item.clip_url);
    mediaUrl = display(item.clip_url); mediaTitle = `Grabación · ${display(item.camera_name)}`; mediaKind = 'video';
  }
  function advanceRecording() {
    if (mediaKind !== 'video' || mediaIndex < 0 || mediaIndex + 1 >= mediaQueue.length) return;
    mediaIndex += 1; const item = mediaQueue[mediaIndex];
    mediaUrl = display(item.clip_url); mediaTitle = `Grabación · ${display(item.camera_name)}`;
  }
  async function saveCameraPermission(permission: CameraPermissionRow) {
    await action(() => api(`/cameras/${cameraId}/permissions`, 'PUT', {user_id: permission.user_id, can_view: Boolean(permission.can_view), can_configure: Boolean(permission.can_configure)}), `Permisos de ${display(permission.email)} guardados.`);
  }
  async function movePtz(actionName: string) {
    busy = true; error = ''; notice = 'Moviendo cámara…';
    const targetId = liveCameraId || cameraId;
    try {
      const queued = await api<{id: string}>(`/cameras/${targetId}/ptz`, 'POST', {action: actionName, speed: 0.5});
      await waitForCommand(queued.id, targetId, 15000);
      notice = 'Movimiento PTZ realizado.';
    } catch (e) { notice = ''; error = (e as Error).message; }
    finally { busy = false; }
  }
  const durationLabel = (value: unknown) => {
    const seconds = Math.max(0, Number(value) || 0);
    return `${Math.floor(seconds / 60)} min ${Math.floor(seconds % 60)} s`;
  };
  function openForm(row?: Row) {
    editing = row?.id || ''; name = display(row?.name || ''); address = display(row?.address || '');
    email = display(row?.email || ''); username = display(row?.username || ''); password = '';
    firstName = display(row?.first_name || ''); lastName = display(row?.last_name || '');
    role = display(row?.role || 'VIEWER'); status = display(row?.status || 'ACTIVE');
    tenantId = display(row?.tenant_id || user?.tenant_id || tenants[0]?.id || '');
    siteId = ''; rtspUrl = ''; integration = 'RTSP'; cameraBrand = 'EZVIZ'; frigateCameras = [];
    cameraModel = ''; cameraHost = ''; cameraUsername = ''; cameraPassword = '';
    cameraDeviceId = ''; frigateName = ''; showForm = true;
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    await action(async () => {
      let data: Record<string, unknown> = {};
      if (section === 'admin/customers') {
        const old = records.find(r => r.id === editing);
        data = { name, legal_name: old?.legal_name || '', tax_id: old?.tax_id || '', timezone: old?.timezone || 'America/Lima' };
        if (editing) data.status = status;
      } else if (section === 'admin/sites') data = { name, tenant_id: tenantId, address, description: records.find(r => r.id === editing)?.description || '' };
      else if (section === 'admin/users') {
        data = editing ? { first_name: firstName, last_name: lastName, role, status } : { tenant_id: tenantId, email, username, password, first_name: firstName, last_name: lastName, role };
      } else if (section === 'cameras') data = {
        name, tenant_id: tenantId, site_id: siteId, integration_type: integration,
        brand: cameraBrand, model: cameraModel, frigate_camera_name: frigateName || null,
        ...(integration === 'RTSP' ? { rtsp_url: rtspUrl } : {}),
        ...(integration === 'V380' ? { host: cameraHost, port: 8800, username: cameraUsername, password: cameraPassword, device_id: cameraDeviceId } : {})
      };
      await api(endpoints[section] + (editing ? `/${editing}` : ''), editing ? 'PUT' : 'POST', data);
      showForm = false; password = ''; cameraPassword = ''; rtspUrl = '';
      [tenants, sites] = await Promise.all([api('/tenants'), api('/sites')]);
    }, editing ? 'Cambios guardados.' : 'Registro creado.');
  }
  const newPermission = () => section === 'admin/customers' ? can('tenants.manage') : section === 'admin/sites' ? can('sites.manage') : section === 'admin/users' ? can('users.manage') : section === 'cameras' ? can('cameras.manage') : false;
  function mountDialog(node: HTMLDialogElement) { node.showModal(); }
</script>

<svelte:head><title>{title} · Vigilay</title></svelte:head>
<div class="app-shell">
  <aside class="sidebar">
    <a href="/dashboard" class="brand"><span class="brand-symbol">V</span> vigilay<span class="brand-dot">.</span></a>
    <span class="workspace-label">CENTRO DE CONTROL</span>
    <nav aria-label="Navegación principal">
      <a href="/dashboard" class:active={section === 'dashboard'}><span>◫</span> Resumen general</a>
      <a href="/cameras" class:active={section.startsWith('cameras')}><span>▣</span> Cámaras</a>
      <a href="/events" class:active={section === 'events'}><span>⚑</span> Eventos de IA</a>
      <a href="/recordings" class:active={section === 'recordings'}><span>◉</span> Grabaciones</a>
      <span class="workspace-label">ADMINISTRACIÓN</span>
      {#if can('tenants.manage')}<a href="/admin/customers" class:active={section === 'admin/customers'}><span>▦</span> Clientes</a>{/if}
      {#if can('sites.manage')}<a href="/admin/sites" class:active={section === 'admin/sites'}><span>⌂</span> Sedes</a>{/if}
      {#if can('users.manage')}<a href="/admin/users" class:active={section === 'admin/users'}><span>♙</span> Usuarios</a>{/if}
      {#if can('audit.read')}<a href="/admin/audit" class:active={section === 'admin/audit'}><span>≡</span> Auditoría</a>{/if}
      {#if can('system.read')}<a href="/admin/system" class:active={section === 'admin/system'}><span>◉</span> Sistema</a>{/if}
    </nav>
    <div class="sidebar-bottom"><span class="avatar">{user?.first_name?.[0] || 'V'}</span><div><a href="/profile">{user?.first_name || 'Mi perfil'}</a><small>{roleLabel(user?.role || '')}</small></div></div>
  </aside>
  <div class="main-area">
    <header class="topbar"><span>Espacio de trabajo <span class="separator">/</span> {user?.tenant_id ? nameOf(tenants, user.tenant_id) : 'Administración central'}</span>
      <button class="text-button" onclick={() => action(async () => { await api('/auth/logout', 'POST'); location.assign('/login'); }, '')}>Cerrar sesión ↗</button>
    </header>
    <main class="content">
      <div class="page-heading"><div><p class="eyebrow">VIGILAY / {cameraId ? 'CÁMARAS' : 'ADMINISTRACIÓN'}</p><h1>{title}</h1><p class="muted">{section === 'dashboard' ? 'La actividad de tus espacios, en un solo lugar.' : 'Gestiona y consulta la información de tu organización.'}</p></div>
        {#if newPermission()}<button class="primary" onclick={() => openForm()}>＋ {section === 'cameras' ? 'Agregar cámara' : 'Crear registro'}</button>{/if}
      </div>
      {#if error}<p class="message error" role="alert">{error}</p>{/if}
      {#if notice}<p class="message success" role="status">{notice}</p>{/if}
      {#if loading}<div class="empty"><span class="pulse"></span><p>Cargando tu espacio de trabajo…</p></div>
      {:else if section === 'dashboard'}
        <div class="metrics">
          {#each [['Clientes', 'tenants'], ['Sedes', 'sites'], ['Cámaras registradas', 'cameras'], ['Cámaras en línea', 'cameras_online']] as [label, key]}
            <article><span>{label}</span><strong>{metrics[key] ?? 0}</strong><small>{key === 'cameras_online' ? 'Incluye simuladores identificados' : 'Registros de tu espacio'}</small></article>
          {/each}
        </div>
        <section class="panel"><div class="panel-heading"><h2>Tus cámaras</h2><a href="/cameras">Ver todas →</a></div>
          {#if !records.length}<div class="empty"><span class="empty-icon">▣</span><h3>Tu centro de control comienza aquí</h3><p>Crea un cliente y una sede, luego registra tu primera cámara.</p>{#if can('tenants.manage')}<a class="button primary" href="/admin/customers">Crear primer cliente →</a>{/if}</div>
          {:else}<div class="camera-grid">{#each records as item}<article class="camera-card"><div class="camera-preview"><span>▣</span><p>{item.status === 'ONLINE' ? 'Lista para transmitir' : stateLabel(item.status)}</p><button class="preview-live" disabled={item.status !== 'ONLINE' || item.integration_type === 'SIMULATOR'} onclick={() => openLive(display(item.id), display(item.name))}>▶ Ver en vivo</button></div><div class="camera-caption"><strong>{display(item.name)}</strong><span class="badge">{stateLabel(item.status)}</span><small>{nameOf(sites, item.site_id)}</small><a href="/cameras/{item.id}">Configuración y detalle →</a></div></article>{/each}</div>{/if}
        </section>
        <section class="panel"><div class="panel-heading"><h2>Notificaciones recientes de Frigate <span class="count">{frigateEvents.length}</span></h2><a href="/events">Ver todos los eventos →</a></div>{#if !frigateEvents.length}<div class="empty"><p>No hay alertas de IA disponibles para tus cámaras.</p></div>{:else}<div class="dashboard-events">{#each frigateEvents as item}<a href="/events"><img src={display(item.thumbnail_url)} alt="" /><span><strong>{eventLabel(item.label)}</strong><small>{display(item.camera_name)} · {new Date(Number(item.start_time) * 1000).toLocaleString('es-PE', {timeZone: 'America/Lima'})}</small></span></a>{/each}</div>{/if}</section>
      {:else if cameraId && camera}
        <div class="detail-title"><h2>{display(camera.name)}</h2><span class="badge">{stateLabel(camera.status)}</span><span class="badge">{camera.integration_type === 'SIMULATOR' ? 'Simulador' : 'RTSP'}</span>{#if camera.integration_type !== 'SIMULATOR'}<button class="primary live-button" disabled={busy} onclick={() => openLive()}>▶ Ver en vivo</button>{/if}</div>
        <p class="message">{camera.integration_type === 'SIMULATOR' ? 'Este dispositivo simula configuración y conectividad. No genera video ni detecciones de personas.' : 'La transmisión Cloudflare se inicia bajo demanda y se detiene cuando ya no quedan espectadores.'}</p>
        {#if can('cameras.configure')}
          <section class="panel"><div class="panel-heading"><h2>Capacidades y configuración</h2><button disabled={busy} onclick={probeCamera}>{busy ? 'Probando…' : 'Probar conexión'}</button></div>
            {#if !capabilities.length}<div class="empty"><p>Aún no se han detectado capacidades. Ejecuta una prueba de conexión.</p></div>{/if}
            {#each capabilities as cap}{#if cap.key === 'motion_sensitivity' && cap.writable}
              <form class="settings-form" onsubmit={(e) => { e.preventDefault(); void action(() => api(`/cameras/${cameraId}/settings`, 'PUT', { motion_sensitivity: sensitivity }), 'Configuración encolada. Se verificará leyendo el dispositivo.'); }}>
                <label>Sensibilidad de movimiento (0–100)<input type="number" min="0" max="100" bind:value={sensitivity} required /></label><button class="primary" disabled={busy}>Aplicar configuración</button>
              </form>{/if}{/each}
            {#each settings as setting}<div class="setting-row"><strong>Sensibilidad de movimiento</strong><span>Deseado: {display(setting.desired)}</span><span>Reportado: {display(setting.reported)}</span><span class="badge">{stateLabel(setting.status)}</span></div>{/each}
          </section>
          <section class="panel"><div class="panel-heading"><h2>Historial de comandos</h2><small>Se actualiza en tiempo real</small></div><div class="table-wrap"><table><thead><tr><th>Comando</th><th>Estado</th><th>Fecha</th><th>Resultado</th></tr></thead><tbody>{#each commands as c}<tr><td>{c.command === 'PROBE' ? 'Probar conexión' : 'Aplicar configuración'}</td><td>{stateLabel(c.status)}</td><td>{new Date(display(c.created_at)).toLocaleString('es-PE', {timeZone: 'America/Lima'})}</td><td>{display(c.error)}</td></tr>{/each}</tbody></table></div></section>
        {/if}
        {#if can('cameras.manage')}<section class="panel"><div class="panel-heading"><div><h2>Frigate: grabación e IA</h2><small>El alias debe existir en el Frigate de esta sede.</small></div></div><form class="settings-form" onsubmit={(e) => {e.preventDefault(); void action(() => api(`/frigate/cameras/${cameraId}`, 'PUT', {frigate_camera_name: frigateName}), 'Cámara vinculada con Frigate.');}}>
          <label>Cámara en Frigate<select bind:value={frigateName} required><option value="">Selecciona una cámara</option>{#each frigateCameras as item}<option value={item.name}>{display(item.name)}</option>{/each}</select></label><button class="primary" disabled={busy || !frigateName}>Vincular</button>
        </form></section>{/if}
        {#if can('cameras.manage')}<section class="panel"><div class="panel-heading"><div><h2>Acceso de usuarios <span class="count">{cameraPermissions.length}</span></h2><small>Una cámara puede asignarse a todos los operadores y observadores necesarios.</small></div></div>
          {#if !cameraPermissions.length}<div class="empty"><p>No hay operadores u observadores activos en esta empresa.</p></div>{:else}<div class="table-wrap"><table><thead><tr><th>Usuario</th><th>Ver cámara</th><th>Controlar/configurar</th><th>Acción</th></tr></thead><tbody>{#each cameraPermissions as permission}<tr><td><strong>{display(permission.first_name)} {display(permission.last_name)}</strong><small>{display(permission.email)}</small></td><td><label class="check"><input type="checkbox" bind:checked={permission.can_view} /> Permitido</label></td><td><label class="check"><input type="checkbox" bind:checked={permission.can_configure} onchange={() => { if (permission.can_configure) permission.can_view = true; }} /> Permitido</label></td><td><button disabled={busy} onclick={() => saveCameraPermission(permission)}>Guardar</button></td></tr>{/each}</tbody></table></div>{/if}
        </section>{/if}
      {:else if section === 'events'}
        <section class="panel"><div class="panel-heading"><div><h2>Alertas y detecciones <span class="count">{filteredEvents.length}</span></h2><small>Resultados reales producidos por la IA de Frigate.</small></div><div class="list-filters">{#if !user?.tenant_id}<select aria-label="Filtrar por empresa" bind:value={eventsTenant} onchange={() => { eventsCameraId = ''; eventsPage = 1; }}><option value="">Todas las empresas</option>{#each tenants as item}<option value={item.id}>{display(item.name)}</option>{/each}</select>{/if}<select aria-label="Filtrar por cámara" bind:value={eventsCameraId} onchange={() => eventsPage = 1}><option value="">Todas las cámaras</option>{#each eventsCameras as item}<option value={item.id}>{display(item.name)}</option>{/each}</select><button disabled={busy} onclick={() => action(refresh, 'Eventos actualizados.')}>Actualizar</button></div></div>
          <div class="panel-heading events-range"><div class="list-filters"><label class="range-label">Desde<input type="datetime-local" bind:value={eventsAfter} onchange={() => action(refresh, 'Eventos actualizados.')} /></label><label class="range-label">Hasta<input type="datetime-local" bind:value={eventsBefore} onchange={() => action(refresh, 'Eventos actualizados.')} /></label></div><div class="list-filters"><button disabled={busy} onclick={() => setEventsRange(0, 0)}>Hoy</button><button disabled={busy} onclick={() => setEventsRange(1, 1)}>Ayer</button><button disabled={busy} onclick={() => setEventsRange(7, 0)}>Últimos 7 días</button>{#if eventsAfter || eventsBefore}<button disabled={busy} onclick={clearEventsRange}>Quitar fechas</button>{/if}</div></div>
          {#if !frigateEvents.length}<div class="empty"><span class="empty-icon">⚑</span><h3>No hay eventos disponibles</h3><p>{eventsAfter || eventsBefore ? 'No hay eventos en el rango de fechas seleccionado.' : 'Vincula cada cámara con su alias de Frigate desde Configuración y detalle.'}</p></div>
          {:else if !filteredEvents.length}<div class="empty"><span class="empty-icon">⚑</span><h3>Sin eventos con estos filtros</h3><p>Prueba con otra empresa o cámara.</p></div>
          {:else}<div class="event-grid">{#each pagedEvents as item}<article class="event-card"><button class="event-image" onclick={() => { mediaIndex = -1; mediaQueue = []; mediaUrl = display(item.thumbnail_url); mediaTitle = `${eventLabel(item.label)} · ${display(item.camera_name)}`; mediaKind = 'image'; }}><img src={display(item.thumbnail_url)} alt="{eventLabel(item.label)} detectado en {display(item.camera_name)}" /></button><div><span class="badge">{eventLabel(item.label)}{item.sub_label ? ` · ${display(item.sub_label)}` : ''}</span><strong>{display(item.camera_name)}</strong><p>{new Date(Number(item.start_time) * 1000).toLocaleString('es-PE', {timeZone: 'America/Lima'})}</p><div class="card-actions">{#if item.clip_url}<button class="primary" onclick={() => { mediaIndex = -1; mediaQueue = []; mediaUrl = display(item.clip_url); mediaTitle = `${eventLabel(item.label)} · ${display(item.camera_name)}`; mediaKind = 'video'; }}>Ver clip</button><a class="button" href={display(item.clip_url)} download={mediaFileName(item, 'evento')} title="Descargar clip">⬇ Descargar</a>{/if}</div></div></article>{/each}</div>
          <div class="pagination"><span>{filteredEvents.length ? `${(eventsPage - 1) * eventsPageSize + 1}–${Math.min(eventsPage * eventsPageSize, filteredEvents.length)} de ${filteredEvents.length}` : '0 eventos'}</span><div><label>Por página <select bind:value={eventsPageSize} onchange={() => eventsPage = 1}><option value={6}>6</option><option value={12}>12</option><option value={24}>24</option></select></label><button disabled={eventsPage <= 1} onclick={() => eventsPage -= 1}>← Anterior</button><span>Página {eventsPage} de {eventsPages}</span><button disabled={eventsPage >= eventsPages} onclick={() => eventsPage += 1}>Siguiente →</button></div></div>{/if}
        </section>
      {:else if section === 'recordings'}
        <section class="panel"><div class="panel-heading"><div><h2>Grabaciones de Frigate <span class="count">{recordings.length}</span></h2><small>Video conservado y procesado por Frigate en la sede. Al terminar un fragmento continúa el siguiente de la lista.</small></div><div class="recording-filter">{#if !user?.tenant_id}<select aria-label="Filtrar por empresa" bind:value={recordingTenant} onchange={() => { recordingSite = ''; frigateCameraId = ''; selectRecordingScope(); }}><option value="">Todas las empresas</option>{#each tenants as item}<option value={item.id}>{display(item.name)}</option>{/each}</select>{/if}<select aria-label="Filtrar por sede" bind:value={recordingSite} onchange={() => { frigateCameraId = ''; selectRecordingScope(); }}><option value="">Todas las sedes</option>{#each sites.filter(item => !recordingTenant || item.tenant_id === recordingTenant) as item}<option value={item.id}>{display(item.name)}</option>{/each}</select><select aria-label="Seleccionar cámara" bind:value={frigateCameraId} onchange={() => action(loadFrigateRecordings, 'Grabaciones actualizadas.')}><option value="">Selecciona una cámara</option>{#each recordingCameras as item}<option value={item.id}>{display(item.name)} · {nameOf(sites, item.site_id)}</option>{/each}</select><button disabled={busy || !frigateCameraId} onclick={() => action(loadFrigateRecordings, 'Grabaciones actualizadas.')}>Actualizar</button></div></div>
          <form class="panel-heading events-range" onsubmit={(event) => { event.preventDefault(); void loadFrigateRecordings(); }}>
            <label class="range-label">Desde (fecha y hora local)<input type="datetime-local" bind:value={recordingAfter} required /></label>
            <label class="range-label">Hasta (fecha y hora local)<input type="datetime-local" bind:value={recordingBefore} required /></label>
            <button class="primary" disabled={recordingsLoading || !frigateCameraId}>Aplicar intervalo</button>
            <small>Zona horaria: {Intl.DateTimeFormat().resolvedOptions().timeZone}. Máximo 7 días.</small>
          </form>
          <p class="storage-note">Origen: disco de Frigate en la sede. La memoria SD interna de la cámara aún no está integrada: necesita un adaptador de reproducción compatible con su modelo; RTSP solo permite el vivo. No se borran ni formatean tarjetas.</p>
          {#if recordingsLoading}<div class="empty" role="status">Consultando grabaciones de la sede…</div>
          {:else if recordingsError}<div class="empty" role="alert"><h3>No se pudo consultar Frigate</h3><p>{recordingsError}</p><button onclick={() => loadFrigateRecordings()}>Reintentar</button></div>
          {:else if !recordings.length}<div class="empty"><span class="empty-icon">◉</span><h3>{frigateCameraId ? 'No hay grabaciones en el intervalo seleccionado' : 'Selecciona una cámara vinculada a Frigate'}</h3><p>Comprueba el intervalo, la vinculación y que Frigate tenga la grabación habilitada.</p></div>
          {:else}<div class="recording-list">{#each pagedRecordings as item}<article><div><strong>{display(item.camera_name)}</strong><p>{new Date(Number(item.start) * 1000).toLocaleString('es-PE')}</p></div><span>{durationLabel(item.duration)}</span><span>{display(item.objects)} objetos · {display(item.motion)} movimientos</span><div class="card-actions"><button class="primary" onclick={() => openRecording(item)}>Reproducir continuo</button><a class="button" href={`${display(item.clip_url)}?download=true`} download={mediaFileName(item, 'grabacion')} title="Descargar grabación">⬇ Descargar</a></div></article>{/each}</div><div class="pagination"><span>Página {recordingPage} de {recordingPages}</span><div><label>Por página <select bind:value={recordingPageSize} onchange={() => recordingPage = 1}><option value={5}>5</option><option value={10}>10</option><option value={20}>20</option></select></label><button disabled={recordingPage <= 1} onclick={() => recordingPage -= 1}>← Anterior</button><button disabled={recordingPage >= recordingPages} onclick={() => recordingPage += 1}>Siguiente →</button></div></div>{/if}
        </section>
      {:else if section === 'admin/system'}
        <section class="panel"><div class="panel-heading"><h2>Servicios</h2><button onclick={() => action(refresh, 'Estado actualizado.')} disabled={busy}>Actualizar</button></div>{#each Object.entries(health) as [service, value]}<div class="setting-row"><strong>{service === 'media' ? 'Video en vivo' : service.toUpperCase()}</strong><span class="badge">{value === 'ok' ? 'Operativo' : value === 'offline' ? 'Sin conexión' : 'Pendiente de integración'}</span></div>{/each}</section>
        {#if user?.role === 'SUPER_ADMIN'}<section class="panel"><div class="panel-heading"><div><h2>Cloudflare Stream</h2><small>Configuración global cifrada; el token nunca vuelve al navegador.</small></div><span class="badge">{cloudflare.configured ? 'Configurado' : 'Sin configurar'}</span></div>
          <form class="settings-form" onsubmit={(e) => {e.preventDefault(); void action(async () => {await api('/admin/integrations/cloudflare', 'PUT', {account_id: cloudflareAccountId, api_token: cloudflareApiToken}); cloudflareApiToken = '';}, 'Credenciales verificadas y guardadas.');}}>
            <label>Account ID<input bind:value={cloudflareAccountId} required maxlength="64" autocomplete="off" /></label>
            <label>API Token<input type="password" bind:value={cloudflareApiToken} required minlength="20" maxlength="256" autocomplete="new-password" /></label>
            <p class="muted">Vigilay verifica las credenciales con Cloudflare antes de cifrarlas. Por seguridad, para cambiarlas debes introducir ambas nuevamente.</p>
            <button class="primary" disabled={busy}>{busy ? 'Verificando…' : 'Verificar y guardar'}</button>
          </form>
        </section>{/if}
      {:else if section === 'profile'}
        <section class="panel profile"><h2>{user?.first_name}</h2><p>{user?.email}</p><p>{roleLabel(user?.role)}</p><h3>Cambiar contraseña</h3>
          <form onsubmit={(e) => {e.preventDefault(); void action(async () => {await api('/auth/change-password', 'POST', {current_password: currentPassword, new_password: newPassword}); location.assign('/login');}, 'Contraseña actualizada.');}}>
            <label>Contraseña actual<input type="password" autocomplete="current-password" bind:value={currentPassword} required /></label><label>Nueva contraseña<input type="password" autocomplete="new-password" minlength="12" bind:value={newPassword} required /></label><button class="primary" disabled={busy}>Cambiar y cerrar las sesiones</button>
          </form>
        </section>
      {:else if section === 'cameras'}
        <section class="panel"><div class="panel-heading"><h2>Cámaras <span class="count">{totalRecords}</span></h2><div class="list-filters">
          <input aria-label="Buscar cámaras" type="search" placeholder="Buscar cámara…" bind:value={search} oninput={scheduleSearch} />
          <select aria-label="Empresa de las cámaras" bind:value={cameraTenant} disabled={!!user?.tenant_id} onchange={() => chooseCameraScope(true)}>{#each tenants as tenant}<option value={tenant.id}>{display(tenant.name)}</option>{/each}</select>
          <select aria-label="Sede de las cámaras" bind:value={cameraSite} onchange={() => chooseCameraScope()}>{#each sites.filter(row => row.tenant_id === cameraTenant) as site}<option value={site.id}>{display(site.name)}</option>{/each}</select>
          <select aria-label="Filtrar por estado" bind:value={filterStatus} onchange={applyFilters}><option value="">Todos los estados</option><option value="ONLINE">En línea</option><option value="OFFLINE">Sin conexión</option><option value="UNVERIFIED">Sin verificar</option></select>
          <select aria-label="Filtrar por integración" bind:value={filterIntegration} onchange={applyFilters}><option value="">Todas las integraciones</option><option value="RTSP">RTSP</option><option value="V380">V380</option><option value="SIMULATOR">Simulador</option></select>
        </div></div>
          {#if !records.length}<div class="empty"><span class="empty-icon">▣</span><h3>No hay cámaras con estos filtros</h3><p>Registra una cámara o cambia los filtros.</p></div>
          {:else}<div class="camera-grid operational">{#each records as item (item.id)}<article class="camera-card">
            {#if item.integration_type !== 'SIMULATOR' && item.enabled !== false}
              <LiveTile cameraId={item.id} enabled={!liveOpen && !camerasLoading && !!cameraTenant && !!cameraSite} />
            {:else}<div class="camera-preview">Cámara deshabilitada o simulador</div>{/if}
            <div class="camera-caption"><strong>{display(item.name)}</strong><span class="badge">{stateLabel(item.status)}</span><small>{nameOf(tenants, item.tenant_id)} · {nameOf(sites, item.site_id)}</small><button disabled={item.integration_type === 'SIMULATOR' || item.enabled === false} onclick={() => openLive(item.id, display(item.name))}>Ampliar / PTZ</button><a href="/cameras/{item.id}">Configuración y detalle →</a></div>
          </article>{/each}</div>{/if}
          <div class="pagination"><span>{totalRecords ? `${(pageNumber - 1) * 4 + 1}–${Math.min(pageNumber * 4, totalRecords)} de ${totalRecords}` : '0 cámaras'} · Hasta 4 vivos visibles; se pausan al ocultar la pestaña.</span><div><button disabled={pageNumber <= 1 || busy || camerasLoading} onclick={() => { pageNumber--; void refresh(); }}>← Anterior</button><span>Página {pageNumber} de {totalPages}</span><button disabled={pageNumber >= totalPages || busy || camerasLoading} onclick={() => { pageNumber++; void refresh(); }}>Siguiente →</button></div></div>
        </section>
      {:else if endpoints[section]}
        <section class="panel"><div class="panel-heading"><h2>{titles[section]} <span class="count">{totalRecords}</span></h2><div class="list-filters">
          <input aria-label="Buscar registros" type="search" placeholder="Buscar…" bind:value={search} oninput={scheduleSearch} />
          {#if user?.role === 'SUPER_ADMIN' && section !== 'admin/customers'}<select aria-label="Filtrar por cliente" bind:value={filterTenant} onchange={applyFilters}><option value="">Todos los clientes</option>{#each tenants as tenant}<option value={tenant.id}>{display(tenant.name)}</option>{/each}</select>{/if}
          {#if section === 'admin/customers'}<select aria-label="Filtrar por estado" bind:value={filterStatus} onchange={applyFilters}><option value="">Todos los estados</option><option value="ACTIVE">Activos</option><option value="SUSPENDED">Suspendidos</option></select>
          {:else if section === 'admin/users'}<select aria-label="Filtrar por estado" bind:value={filterStatus} onchange={applyFilters}><option value="">Todos los estados</option><option value="ACTIVE">Activos</option><option value="DISABLED">Deshabilitados</option></select>
          {:else if section === 'cameras'}<select aria-label="Filtrar por estado" bind:value={filterStatus} onchange={applyFilters}><option value="">Todos los estados</option><option value="ONLINE">En línea</option><option value="OFFLINE">Sin conexión</option><option value="UNVERIFIED">Sin verificar</option></select><select aria-label="Filtrar por integración" bind:value={filterIntegration} onchange={applyFilters}><option value="">Todas las integraciones</option><option value="RTSP">RTSP</option><option value="V380">V380</option><option value="SIMULATOR">Simulador</option></select>{/if}
          <select aria-label="Registros por página" bind:value={pageSize} onchange={applyFilters}><option value={10}>10 por página</option><option value={25}>25 por página</option><option value={50}>50 por página</option></select>
        </div></div>
          {#if !filtered.length}<div class="empty"><span class="empty-icon">▦</span><h3>{records.length ? 'Sin coincidencias' : 'Todavía no hay registros'}</h3><p>{records.length ? 'Prueba con otro término de búsqueda.' : 'Los registros que crees aparecerán aquí.'}</p></div>
          {:else}<div class="table-wrap"><table><thead><tr><th>{section === 'admin/audit' ? 'Acción' : 'Nombre'}</th><th>{section === 'admin/users' ? 'Correo' : section === 'admin/audit' ? 'Recurso' : 'Cliente / detalle'}</th><th>{section === 'admin/users' ? 'Rol' : section === 'admin/audit' ? 'Fecha' : 'Estado / ubicación'}</th><th>Acciones</th></tr></thead><tbody>
            {#each filtered as row}<tr><td><strong>{display(row.name || row.first_name || row.email || row.action)}</strong>{#if row.integration_type}<small>{row.integration_type === 'SIMULATOR' ? 'Simulador de desarrollo' : 'RTSP'}</small>{/if}</td><td>{section === 'admin/users' ? display(row.email) : section === 'admin/customers' ? display(row.timezone) : section === 'admin/audit' ? display(row.resource_type) : nameOf(tenants, row.tenant_id)}</td><td>{section === 'admin/users' ? roleLabel(row.role) : section === 'admin/audit' ? new Date(display(row.created_at)).toLocaleString('es-PE', {timeZone: 'America/Lima'}) : stateLabel(row.status || row.address || '—')}</td><td>{#if section === 'cameras'}<a href="/cameras/{row.id}">Ver detalle →</a>{:else if newPermission() && row.role !== 'SUPER_ADMIN' && row.id !== user?.id}<button class="text-button" onclick={() => openForm(row)}>Editar</button>{:else}—{/if}</td></tr>{/each}
          </tbody></table></div>{/if}
          <div class="pagination"><span>{totalRecords ? `${(pageNumber - 1) * pageSize + 1}–${Math.min(pageNumber * pageSize, totalRecords)} de ${totalRecords}` : '0 registros'}</span><div><button disabled={pageNumber <= 1 || busy} onclick={() => { pageNumber--; void refresh(); }}>← Anterior</button><span>Página {pageNumber} de {totalPages}</span><button disabled={pageNumber >= totalPages || busy} onclick={() => { pageNumber++; void refresh(); }}>Siguiente →</button></div></div>
        </section>
      {:else}<div class="empty"><h2>Página no encontrada</h2><a href="/dashboard">Volver al resumen</a></div>{/if}
    </main>
  </div>
</div>

{#if showForm}
  <dialog class="modal" aria-labelledby="form-title" use:mountDialog onclose={() => showForm = false}>
    <div class="panel-heading"><h2 id="form-title">{editing ? 'Editar registro' : section === 'cameras' ? 'Agregar cámara' : 'Crear registro'}</h2><button class="text-button" onclick={() => showForm = false} aria-label="Cerrar formulario">✕</button></div>
    <form onsubmit={save}>
      {#if section !== 'admin/customers'}<label>Cliente<select bind:value={tenantId} required disabled={!!editing || !!user?.tenant_id} onchange={() => siteId = ''}><option value="">Selecciona un cliente</option>{#each tenants as t}<option value={t.id}>{display(t.name)}</option>{/each}</select></label>{/if}
      {#if section === 'admin/users'}
        {#if !editing}<label>Correo<input type="email" bind:value={email} required /></label><label>Usuario<input bind:value={username} required minlength="3" pattern="[a-zA-Z0-9_.-]+" /></label><label>Contraseña inicial<input type="password" bind:value={password} required minlength="12" autocomplete="new-password" /></label>{/if}
        <div class="form-grid"><label>Nombres<input bind:value={firstName} /></label><label>Apellidos<input bind:value={lastName} /></label></div>
        <label>Rol<select bind:value={role}><option value="VIEWER">Observador</option><option value="OPERATOR">Operador</option><option value="CLIENT_ADMIN">Administrador de cliente</option></select></label>
      {:else}<label>{section === 'cameras' ? 'Alias' : 'Nombre'}<input bind:value={name} required maxlength="160" placeholder={section === 'cameras' ? 'Ej. Entrada principal' : ''} /></label>{/if}
      {#if editing && (section === 'admin/customers' || section === 'admin/users')}<label>Estado<select bind:value={status}><option value="ACTIVE">Activo</option><option value={section === 'admin/users' ? 'DISABLED' : 'SUSPENDED'}>{section === 'admin/users' ? 'Deshabilitado' : 'Suspendido'}</option></select></label>{/if}
      {#if section === 'admin/sites'}<label>Dirección<input bind:value={address} maxlength="300" /></label>{/if}
      {#if section === 'cameras'}
        <label>Sede<select bind:value={siteId} required onchange={() => loadFrigateCatalog(siteId)}><option value="">Selecciona una sede</option>{#each sites.filter(s => s.tenant_id === tenantId) as s}<option value={s.id}>{display(s.name)}</option>{/each}</select></label>
        <div class="form-grid"><label>Marca<select bind:value={cameraBrand} onchange={() => integration = cameraBrand === 'V380' ? 'V380' : 'RTSP'}><option value="EZVIZ">EZVIZ</option><option value="IMOU">Imou</option><option value="V380">V380 Pro</option><option value="GENERIC">RTSP genérica</option></select></label><label>Modelo<input bind:value={cameraModel} maxlength="120" placeholder="Modelo exacto" /></label></div>
        <label>Método de integración<select bind:value={integration}><option value="RTSP">RTSP</option><option value="V380">Puente local V380</option><option value="SIMULATOR">Simulador de desarrollo</option></select></label>
        <label>Cámara de Frigate (opcional)<select bind:value={frigateName}><option value="">Vincular después</option>{#each frigateCameras as item}<option value={item.name}>{display(item.name)}</option>{/each}</select></label>
        {#if integration === 'RTSP'}<label>URL RTSP<input type="password" bind:value={rtspUrl} required autocomplete="off" placeholder="rtsp://usuario:clave@direccion/ruta" /></label><p class="muted">La URL y sus credenciales se guardarán cifradas en MySQL.</p>{:else if integration === 'SIMULATOR'}<p class="muted">Permite probar comandos y configuración sin conectar una cámara física.</p>{/if}
        {#if integration === 'V380'}<div class="form-grid"><label>Dirección IP<input bind:value={cameraHost} required placeholder="192.168.1.100" /></label><label>ID del dispositivo<input bind:value={cameraDeviceId} required maxlength="32" /></label><label>Usuario<input bind:value={cameraUsername} required maxlength="160" /></label><label>Contraseña<input type="password" bind:value={cameraPassword} required autocomplete="off" /></label></div><p class="muted">En varios modelos V380 el usuario coincide con el ID. La contraseña se cifra antes de almacenarse en MySQL.</p>{/if}
      {/if}
      {#if error}<p class="message error" role="alert">{error}</p>{/if}
      <div class="form-actions"><button type="button" onclick={() => showForm = false}>Cancelar</button><button class="primary" disabled={busy}>{busy ? 'Guardando…' : 'Guardar'}</button></div>
    </form>
  </dialog>
{/if}

{#if liveOpen}
  <dialog class="live-modal" aria-labelledby="live-title" use:mountDialog onclose={closeLive}>
    <div class="panel-heading"><div><h2 id="live-title">{liveCameraName}</h2><span class="live-state"><i class:active={liveStatus === 'live'}></i>{liveStatus === 'starting' || liveStatus === 'connecting' ? 'Conectando…' : liveStatus === 'live' ? 'En vivo' : liveStatus === 'reconnecting' ? 'Reconectando…' : liveStatus === 'error' ? 'Error' : 'Cámara sin conexión'}</span></div><button class="text-button" onclick={closeLive} aria-label="Cerrar video">✕</button></div>
    <div class="live-stage">
      {#if liveUrl && !['error', 'stopped'].includes(liveStatus)}<WhepPlayer playbackUrl={liveUrl} onState={(state) => { if (state !== 'connecting') liveStatus = state; }} />
      {:else if liveStatus === 'error'}<p>No se pudo iniciar la transmisión. Revisa el estado del agente y de la cámara.</p>
      {:else}<span class="pulse"></span><p>Preparando transmisión segura…</p>{/if}
    </div>
    {#if can('cameras.configure')}<div class="ptz-controls" aria-label="Control PTZ"><button onclick={() => movePtz('up-left')}>↖</button><button onclick={() => movePtz('up')}>↑</button><button onclick={() => movePtz('up-right')}>↗</button><button onclick={() => movePtz('left')}>←</button><button disabled>PTZ</button><button onclick={() => movePtz('right')}>→</button><button onclick={() => movePtz('down-left')}>↙</button><button onclick={() => movePtz('down')}>↓</button><button onclick={() => movePtz('down-right')}>↘</button><button onclick={() => movePtz('zoom-out')}>− Zoom</button><button onclick={() => movePtz('zoom-in')}>+ Zoom</button></div>{/if}
  </dialog>
{/if}

{#if mediaUrl}
  <dialog class="live-modal" aria-labelledby="media-title" use:mountDialog onclose={() => mediaUrl = ''}>
    <div class="panel-heading"><div><h2 id="media-title">{mediaTitle}</h2><span class="live-state">Contenido servido por Frigate a través de Vigilay</span></div><button class="text-button" onclick={() => mediaUrl = ''} aria-label="Cerrar contenido">✕</button></div>
    <div class="media-stage">{#if mediaKind === 'image'}<img src={mediaUrl} alt={mediaTitle} />{:else}<video src={mediaUrl} controls autoplay playsinline onended={advanceRecording}><track kind="captions" /></video>{/if}</div>
  </dialog>
{/if}

<style>
  .storage-note { padding: 12px 24px; color: var(--muted); font-size: 13px; }
  .list-filters { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
  .list-filters input, .list-filters select { width: auto; min-width: 150px; margin: 0; }
  .list-filters input { min-width: 220px; }
  .pagination { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 24px; border-top: 1px solid var(--border, #e3e8ec); color: #687985; font-size: 13px; }
  .pagination div { display: flex; align-items: center; gap: 12px; }
  .pagination button { margin: 0; }
  @media (max-width: 720px) {
    .list-filters, .list-filters input, .list-filters select { width: 100%; }
    .pagination { align-items: stretch; flex-direction: column; }
    .pagination div { justify-content: space-between; }
    .events-range { flex-direction: column; align-items: stretch; }
    .range-label { width: 100%; }
  }
  .live-button { margin-left: auto; }
  .preview-live { margin-top: 10px; background: #147d74; border-color: #147d74; color: white; }
  .camera-caption a { display: inline-block; margin-top: 12px; font-size: 11px; }
  .camera-grid.operational .camera-preview { min-height: 210px; }
  .event-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; padding: 24px; }
  .dashboard-events { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; padding: 18px 24px 24px; }
  .dashboard-events a { display: flex; align-items: center; gap: 10px; color: inherit; border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
  .dashboard-events img { width: 72px; height: 48px; border-radius: 6px; object-fit: cover; background: #182937; }
  .dashboard-events small { display: block; margin-top: 5px; color: var(--muted); font-size: 10px; }
  .event-card { border: 1px solid var(--line); border-radius: 9px; overflow: hidden; }
  .event-image { display: block; width: 100%; height: 165px; padding: 0; border: 0; border-radius: 0; background: #182937; }
  .event-image img { width: 100%; height: 100%; object-fit: cover; }
  .event-card > div { padding: 15px; }
  .event-card strong { display: block; margin-top: 10px; }
  .event-card p { color: var(--muted); font-size: 11px; }
  .card-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
  .card-actions .button, a.button { display: inline-flex; align-items: center; margin: 0; padding: 8px 14px; border: 1px solid var(--line, #d7dde2); border-radius: 6px; color: inherit; text-decoration: none; font-size: 13px; background: white; }
  .events-range { border-top: 1px solid var(--line, #e3e8ec); flex-wrap: wrap; gap: 10px; }
  .range-label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: var(--muted); margin: 0; }
  .range-label input { margin: 0; }
  .recording-filter { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
  .recording-filter select { min-width: 180px; width: auto; }
  .recording-list article { display: grid; grid-template-columns: minmax(180px, 1fr) auto auto auto; gap: 20px; align-items: center; padding: 16px 24px; border-top: 1px solid var(--line); }
  .recording-list p { margin: 5px 0 0; color: var(--muted); font-size: 11px; }
  .live-modal { width: min(1100px, 94vw); border: 0; padding: 0; border-radius: 12px; background: #101820; color: white; box-shadow: 0 24px 90px #0008; }
  .live-modal::backdrop { background: #081018cc; backdrop-filter: blur(4px); }
  .live-modal :global(.panel-heading) { background: #14222d; border-color: #263a47; }
  .live-modal :global(.text-button) { color: white; }
  .live-state { display: block; font-size: 11px; color: #a9bbc6; margin-top: 6px; }
  .live-state i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #7e8c95; margin-right: 7px; }
  .live-state i.active { background: #36d18c; box-shadow: 0 0 9px #36d18c; }
  .live-stage { min-height: 520px; display: flex; align-items: center; justify-content: center; flex-direction: column; color: #a9bbc6; }
  .live-stage :global(video) { display: block; width: 100%; max-height: 74vh; background: black; }
  .ptz-controls { display: grid; grid-template-columns: repeat(3, 48px); justify-content: center; gap: 7px; padding: 14px; background: #14222d; }
  .ptz-controls button { min-height: 42px; padding: 6px; background: #203642; color: white; border-color: #36505e; }
  .ptz-controls button:nth-last-child(-n+2) { grid-column: span 1; width: 80px; }
  .media-stage { background: black; min-height: 420px; display: grid; place-items: center; }
  .media-stage img, .media-stage video { display: block; max-width: 100%; max-height: 78vh; }
  @media (max-width: 800px) {
    .event-grid, .dashboard-events { grid-template-columns: 1fr; }
    .recording-filter { width: 100%; }
    .recording-filter select { min-width: 0; }
    .recording-list article { grid-template-columns: 1fr; gap: 8px; }
  }
</style>
