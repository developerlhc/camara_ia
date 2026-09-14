<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { api, setCsrf, type Me, type Row } from '$lib/api';
  import WhepPlayer from '$lib/WhepPlayer.svelte';

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
  let mediaQueue = $state<Row[]>([]); let mediaIndex = $state(-1);
  let liveTimer: ReturnType<typeof setTimeout> | undefined;
  let filtered = $derived(records);
  let recordingCameras = $derived(records.filter(row => row.frigate_camera_name && (!recordingTenant || row.tenant_id === recordingTenant) && (!recordingSite || row.site_id === recordingSite)));
  let recordingPages = $derived(Math.max(1, Math.ceil(recordings.length / recordingPageSize)));
  let pagedRecordings = $derived(recordings.slice((recordingPage - 1) * recordingPageSize, recordingPage * recordingPageSize));
  const display = (value: unknown) => value === null || value === undefined ? '—' : String(value);
  const nameOf = (rows: Row[], id: unknown) => display(rows.find(r => r.id === id)?.name || '—');
  const can = (key: string) => user?.permissions.includes(key) || false;
  const stateLabel = (value: unknown) => ({ ACTIVE: 'Activo', SUSPENDED: 'Suspendido', DISABLED: 'Deshabilitado', ONLINE: 'En línea', OFFLINE: 'Sin conexión', UNVERIFIED: 'Sin verificar', SYNCED: 'Sincronizado', DRIFTED: 'Configuración diferente', PENDING: 'Pendiente', RUNNING: 'Ejecutando', SUCCEEDED: 'Completado', FAILED: 'Falló', ERROR: 'Error' }[String(value)] || display(value));
  const roleLabel = (value: unknown) => ({ SUPER_ADMIN: 'Superadministrador', CLIENT_ADMIN: 'Administrador de cliente', OPERATOR: 'Operador', VIEWER: 'Observador' }[String(value)] || display(value));

  async function loadRecords() {
    const params = new URLSearchParams({ paged: 'true', page: String(pageNumber), page_size: String(pageSize) });
    if (search.trim()) params.set('q', search.trim());
    if (filterTenant) params.set('tenant_id', filterTenant);
    if (filterStatus) params.set('status', filterStatus);
    if (filterIntegration && section === 'cameras') params.set('integration_type', filterIntegration);
    const result = await api<{items: Row[]; total: number; pages: number}>(`${endpoints[section]}?${params}`);
    records = result.items; totalRecords = result.total; totalPages = result.pages;
    if (pageNumber > totalPages) { pageNumber = totalPages; await loadRecords(); }
  }

  function applyFilters() { pageNumber = 1; void refresh().catch(e => error = e.message); }
  function scheduleSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilters, 300);
  }

  async function refresh() {
    error = '';
    if (cameraId) {
      camera = await api<Row>(`/cameras/${cameraId}`);
      frigateName = display(camera.frigate_camera_name || '');
      capabilities = await api(`/cameras/${cameraId}/capabilities`);
      if (can('cameras.configure')) {
        settings = await api(`/cameras/${cameraId}/settings`);
        commands = await api(`/cameras/${cameraId}/commands`);
      }
      if (can('cameras.manage')) cameraPermissions = await api<CameraPermissionRow[]>(`/cameras/${cameraId}/permissions`);
    } else if (section === 'dashboard') {
      [metrics, records, frigateEvents] = await Promise.all([
        api<Record<string, number>>('/dashboard'), api('/cameras'),
        api<Row[]>('/frigate/events?limit=6').catch(() => []),
      ]);
    } else if (section === 'events') {
      [records, frigateEvents] = await Promise.all([api('/cameras'), api('/frigate/events?limit=100')]);
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
  onMount(() => {
    let timer: ReturnType<typeof setInterval>;
    const stopOnExit = () => { if (liveOpen) void closeLive(); };
    window.addEventListener('pagehide', stopOnExit);
    void (async () => {
      try {
        user = await api<Me>('/me'); setCsrf(user.csrf_token);
        [tenants, sites] = await Promise.all([api('/tenants'), api('/sites')]);
        if (can('cameras.configure')) frigateCameras = await api('/frigate/cameras').catch(() => []);
        tenantId = user.tenant_id || tenants[0]?.id || '';
        await refresh();
        if (cameraId) timer = setInterval(() => { void refresh().catch(e => error = e.message); }, 3000);
      } catch(e) { error = (e as Error).message; } finally { loading = false; }
    })();
    return () => { clearInterval(timer); clearTimeout(searchTimer); window.removeEventListener('pagehide', stopOnExit); stopOnExit(); };
  });

  async function action(work: () => Promise<unknown>, message: string) {
    busy = true; error = ''; notice = '';
    try { await work(); notice = message; await refresh(); }
    catch(e) { error = (e as Error).message; } finally { busy = false; }
  }
  async function probeCamera() {
    busy = true; error = ''; notice = 'Comprobando la conexión con la cámara…';
    try {
      const queued = await api<{id: string}>(`/cameras/${cameraId}/probe`, 'POST');
      for (let attempt = 0; attempt < 15; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        commands = await api<Row[]>(`/cameras/${cameraId}/commands`);
        const result = commands.find(command => command.id === queued.id);
        if (result?.status === 'SUCCEEDED') {
          await refresh();
          notice = 'Conexión exitosa. La cámara está en línea.';
          return;
        }
        if (result && ['FAILED', 'TIMEOUT', 'CANCELLED'].includes(String(result.status))) {
          throw new Error(`No se pudo conectar con la cámara: ${display(result.error)}`);
        }
      }
      throw new Error('La prueba sigue pendiente. Revisa que el agente local esté iniciado.');
    } catch(e) { notice = ''; error = (e as Error).message; }
    finally { busy = false; }
  }
  async function openLive(targetId = cameraId, targetName = display(camera?.name)) {
    liveCameraId = targetId; liveCameraName = targetName;
    liveOpen = true; liveStatus = 'connecting'; error = '';
    try {
      const result = await api<Record<string, string>>(`/cameras/${targetId}/live/start`, 'POST');
      liveUrl = result.playbackUrl; liveSessionId = result.sessionId;
      liveViewerKey = result.viewerKey; liveStatus = result.status;
      scheduleLiveHeartbeat();
    } catch (e) { liveStatus = 'error'; error = (e as Error).message; }
  }
  function scheduleLiveHeartbeat() {
    clearTimeout(liveTimer);
    if (!liveOpen || !liveSessionId || ['error', 'stopped'].includes(liveStatus)) return;
    liveTimer = setTimeout(async () => {
      try {
        const state = await api<Record<string, string>>(`/cameras/${liveCameraId}/live/heartbeat`, 'POST', {session_id: liveSessionId, viewer_key: liveViewerKey});
        liveStatus = state.status; scheduleLiveHeartbeat();
      } catch (e) { liveStatus = 'error'; error = (e as Error).message; }
    }, liveStatus === 'starting' ? 2000 : 15000);
  }
  async function closeLive() {
    const sessionId = liveSessionId; const viewerKey = liveViewerKey; const targetId = liveCameraId;
    clearTimeout(liveTimer); liveOpen = false; liveStatus = 'stopped'; liveUrl = ''; liveSessionId = ''; liveViewerKey = '';
    if (sessionId && viewerKey && targetId) {
      await api(`/cameras/${targetId}/live/stop`, 'POST', {session_id: sessionId, viewer_key: viewerKey}).catch(() => {});
    }
    liveCameraId = ''; liveCameraName = '';
  }
  async function loadFrigateRecordings() {
    recordings = [];
    recordingPage = 1;
    if (!frigateCameraId) return;
    const before = Math.floor(Date.now() / 1000);
    const after = before - 86400;
    recordings = await api<Row[]>(`/frigate/recordings?camera_id=${encodeURIComponent(frigateCameraId)}&after=${after}&before=${before}`);
  }
  function selectRecordingScope() {
    recordingPage = 1; recordings = [];
    if (frigateCameraId && !recordingCameras.some(row => row.id === frigateCameraId)) frigateCameraId = '';
    if (!frigateCameraId && recordingCameras.length) frigateCameraId = display(recordingCameras[0].id);
    if (frigateCameraId) void action(loadFrigateRecordings, 'Grabaciones actualizadas.');
  }
  function openRecording(item: Row) {
    mediaQueue = [...recordings]; mediaIndex = mediaQueue.findIndex(row => row.clip_url === item.clip_url);
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
      for (let attempt = 0; attempt < 12; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, 500));
        const history = await api<Row[]>(`/cameras/${targetId}/commands`);
        const result = history.find(command => command.id === queued.id);
        if (result?.status === 'SUCCEEDED') { notice = 'Movimiento PTZ realizado.'; return; }
        if (result?.status === 'FAILED') throw new Error(display(result.error));
      }
      throw new Error('El agente local no confirmó el movimiento PTZ.');
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
    siteId = ''; rtspUrl = ''; integration = 'RTSP'; cameraBrand = 'EZVIZ';
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
    <a href="/dashboard" class="brand" data-sveltekit-reload><span class="brand-symbol">V</span> vigilay<span class="brand-dot">.</span></a>
    <span class="workspace-label">CENTRO DE CONTROL</span>
    <nav aria-label="Navegación principal">
      <a href="/dashboard" class:active={section === 'dashboard'} data-sveltekit-reload><span>◫</span> Resumen general</a>
      <a href="/cameras" class:active={section.startsWith('cameras')} data-sveltekit-reload><span>▣</span> Cámaras</a>
      <a href="/events" class:active={section === 'events'} data-sveltekit-reload><span>⚑</span> Eventos de IA</a>
      <a href="/recordings" class:active={section === 'recordings'} data-sveltekit-reload><span>◉</span> Grabaciones</a>
      <span class="workspace-label">ADMINISTRACIÓN</span>
      {#if can('tenants.manage')}<a href="/admin/customers" class:active={section === 'admin/customers'} data-sveltekit-reload><span>▦</span> Clientes</a>{/if}
      {#if can('sites.manage')}<a href="/admin/sites" class:active={section === 'admin/sites'} data-sveltekit-reload><span>⌂</span> Sedes</a>{/if}
      {#if can('users.manage')}<a href="/admin/users" class:active={section === 'admin/users'} data-sveltekit-reload><span>♙</span> Usuarios</a>{/if}
      {#if can('audit.read')}<a href="/admin/audit" class:active={section === 'admin/audit'} data-sveltekit-reload><span>≡</span> Auditoría</a>{/if}
      {#if can('system.read')}<a href="/admin/system" class:active={section === 'admin/system'} data-sveltekit-reload><span>◉</span> Sistema</a>{/if}
    </nav>
    <div class="sidebar-bottom"><span class="avatar">{user?.first_name?.[0] || 'V'}</span><div><a href="/profile" data-sveltekit-reload>{user?.first_name || 'Mi perfil'}</a><small>{roleLabel(user?.role || '')}</small></div></div>
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
        <section class="panel"><div class="panel-heading"><h2>Tus cámaras</h2><a href="/cameras" data-sveltekit-reload>Ver todas →</a></div>
          {#if !records.length}<div class="empty"><span class="empty-icon">▣</span><h3>Tu centro de control comienza aquí</h3><p>Crea un cliente y una sede, luego registra tu primera cámara.</p>{#if can('tenants.manage')}<a class="button primary" href="/admin/customers" data-sveltekit-reload>Crear primer cliente →</a>{/if}</div>
          {:else}<div class="camera-grid">{#each records as item}<article class="camera-card"><div class="camera-preview"><span>▣</span><p>{item.status === 'ONLINE' ? 'Lista para transmitir' : stateLabel(item.status)}</p><button class="preview-live" disabled={item.status !== 'ONLINE' || item.integration_type === 'SIMULATOR'} onclick={() => openLive(display(item.id), display(item.name))}>▶ Ver en vivo</button></div><div class="camera-caption"><strong>{display(item.name)}</strong><span class="badge">{stateLabel(item.status)}</span><small>{nameOf(sites, item.site_id)}</small><a href="/cameras/{item.id}" data-sveltekit-reload>Configuración y detalle →</a></div></article>{/each}</div>{/if}
        </section>
        <section class="panel"><div class="panel-heading"><h2>Notificaciones recientes de Frigate <span class="count">{frigateEvents.length}</span></h2><a href="/events" data-sveltekit-reload>Ver todos los eventos →</a></div>{#if !frigateEvents.length}<div class="empty"><p>No hay alertas de IA disponibles para tus cámaras.</p></div>{:else}<div class="dashboard-events">{#each frigateEvents as item}<a href="/events" data-sveltekit-reload><img src={display(item.thumbnail_url)} alt="" /><span><strong>{display(item.label)}</strong><small>{display(item.camera_name)} · {new Date(Number(item.start_time) * 1000).toLocaleString('es-PE', {timeZone: 'America/Lima'})}</small></span></a>{/each}</div>{/if}</section>
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
          <section class="panel"><div class="panel-heading"><h2>Historial de comandos</h2><small>Actualización cada 3 segundos</small></div><div class="table-wrap"><table><thead><tr><th>Comando</th><th>Estado</th><th>Fecha</th><th>Resultado</th></tr></thead><tbody>{#each commands as c}<tr><td>{c.command === 'PROBE' ? 'Probar conexión' : 'Aplicar configuración'}</td><td>{stateLabel(c.status)}</td><td>{new Date(display(c.created_at)).toLocaleString('es-PE', {timeZone: 'America/Lima'})}</td><td>{display(c.error)}</td></tr>{/each}</tbody></table></div></section>
        {/if}
        {#if can('cameras.manage')}<section class="panel"><div class="panel-heading"><div><h2>Frigate: grabación e IA</h2><small>El alias debe existir en el Frigate de esta sede.</small></div></div><form class="settings-form" onsubmit={(e) => {e.preventDefault(); void action(() => api(`/frigate/cameras/${cameraId}`, 'PUT', {frigate_camera_name: frigateName}), 'Cámara vinculada con Frigate.');}}>
          <label>Cámara en Frigate<select bind:value={frigateName} required><option value="">Selecciona una cámara</option>{#each frigateCameras as item}<option value={item.name}>{display(item.name)}</option>{/each}</select></label><button class="primary" disabled={busy || !frigateName}>Vincular</button>
        </form></section>{/if}
        {#if can('cameras.manage')}<section class="panel"><div class="panel-heading"><div><h2>Acceso de usuarios <span class="count">{cameraPermissions.length}</span></h2><small>Una cámara puede asignarse a todos los operadores y observadores necesarios.</small></div></div>
          {#if !cameraPermissions.length}<div class="empty"><p>No hay operadores u observadores activos en esta empresa.</p></div>{:else}<div class="table-wrap"><table><thead><tr><th>Usuario</th><th>Ver cámara</th><th>Controlar/configurar</th><th>Acción</th></tr></thead><tbody>{#each cameraPermissions as permission}<tr><td><strong>{display(permission.first_name)} {display(permission.last_name)}</strong><small>{display(permission.email)}</small></td><td><label class="check"><input type="checkbox" bind:checked={permission.can_view} /> Permitido</label></td><td><label class="check"><input type="checkbox" bind:checked={permission.can_configure} onchange={() => { if (permission.can_configure) permission.can_view = true; }} /> Permitido</label></td><td><button disabled={busy} onclick={() => saveCameraPermission(permission)}>Guardar</button></td></tr>{/each}</tbody></table></div>{/if}
        </section>{/if}
      {:else if section === 'events'}
        <section class="panel"><div class="panel-heading"><div><h2>Alertas y detecciones <span class="count">{frigateEvents.length}</span></h2><small>Resultados reales producidos por la IA de Frigate.</small></div><button disabled={busy} onclick={() => action(refresh, 'Eventos actualizados.')}>Actualizar</button></div>
          {#if !frigateEvents.length}<div class="empty"><span class="empty-icon">⚑</span><h3>No hay eventos disponibles</h3><p>Vincula cada cámara con su alias de Frigate desde Configuración y detalle.</p></div>
          {:else}<div class="event-grid">{#each frigateEvents as item}<article class="event-card"><button class="event-image" onclick={() => { mediaIndex = -1; mediaQueue = []; mediaUrl = display(item.thumbnail_url); mediaTitle = `${display(item.label)} · ${display(item.camera_name)}`; mediaKind = 'image'; }}><img src={display(item.thumbnail_url)} alt="{display(item.label)} detectado en {display(item.camera_name)}" /></button><div><span class="badge">{display(item.label)}</span><strong>{display(item.camera_name)}</strong><p>{new Date(Number(item.start_time) * 1000).toLocaleString('es-PE', {timeZone: 'America/Lima'})}</p>{#if item.clip_url}<button class="primary" onclick={() => { mediaIndex = -1; mediaQueue = []; mediaUrl = display(item.clip_url); mediaTitle = `${display(item.label)} · ${display(item.camera_name)}`; mediaKind = 'video'; }}>Ver clip</button>{/if}</div></article>{/each}</div>{/if}
        </section>
      {:else if section === 'recordings'}
        <section class="panel"><div class="panel-heading"><div><h2>Grabaciones de Frigate <span class="count">{recordings.length}</span></h2><small>Video conservado y procesado por Frigate en la sede. Al terminar un fragmento continúa el siguiente de la lista.</small></div><div class="recording-filter">{#if !user?.tenant_id}<select aria-label="Filtrar por empresa" bind:value={recordingTenant} onchange={() => { recordingSite = ''; frigateCameraId = ''; selectRecordingScope(); }}><option value="">Todas las empresas</option>{#each tenants as item}<option value={item.id}>{display(item.name)}</option>{/each}</select>{/if}<select aria-label="Filtrar por sede" bind:value={recordingSite} onchange={() => { frigateCameraId = ''; selectRecordingScope(); }}><option value="">Todas las sedes</option>{#each sites.filter(item => !recordingTenant || item.tenant_id === recordingTenant) as item}<option value={item.id}>{display(item.name)}</option>{/each}</select><select aria-label="Seleccionar cámara" bind:value={frigateCameraId} onchange={() => action(loadFrigateRecordings, 'Grabaciones actualizadas.')}><option value="">Selecciona una cámara</option>{#each recordingCameras as item}<option value={item.id}>{display(item.name)} · {nameOf(sites, item.site_id)}</option>{/each}</select><button disabled={busy || !frigateCameraId} onclick={() => action(loadFrigateRecordings, 'Grabaciones actualizadas.')}>Actualizar</button></div></div>
          {#if !recordings.length}<div class="empty"><span class="empty-icon">◉</span><h3>No hay grabaciones en las últimas 24 horas</h3><p>Comprueba que la cámara esté vinculada y que Frigate tenga la grabación habilitada.</p></div>
          {:else}<div class="recording-list">{#each pagedRecordings as item}<article><div><strong>{display(item.camera_name)}</strong><p>{new Date(Number(item.start) * 1000).toLocaleString('es-PE', {timeZone: 'America/Lima'})}</p></div><span>{durationLabel(item.duration)}</span><span>{display(item.objects)} objetos · {display(item.motion)} movimientos</span><button class="primary" onclick={() => openRecording(item)}>Reproducir continuo</button></article>{/each}</div><div class="pagination"><span>Página {recordingPage} de {recordingPages}</span><div><label>Por página <select bind:value={recordingPageSize} onchange={() => recordingPage = 1}><option value={5}>5</option><option value={10}>10</option><option value={20}>20</option></select></label><button disabled={recordingPage <= 1} onclick={() => recordingPage -= 1}>← Anterior</button><button disabled={recordingPage >= recordingPages} onclick={() => recordingPage += 1}>Siguiente →</button></div></div>{/if}
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
          {#if user?.role === 'SUPER_ADMIN'}<select aria-label="Filtrar por cliente" bind:value={filterTenant} onchange={applyFilters}><option value="">Todos los clientes</option>{#each tenants as tenant}<option value={tenant.id}>{display(tenant.name)}</option>{/each}</select>{/if}
          <select aria-label="Filtrar por estado" bind:value={filterStatus} onchange={applyFilters}><option value="">Todos los estados</option><option value="ONLINE">En línea</option><option value="OFFLINE">Sin conexión</option><option value="UNVERIFIED">Sin verificar</option></select>
          <select aria-label="Filtrar por integración" bind:value={filterIntegration} onchange={applyFilters}><option value="">Todas las integraciones</option><option value="RTSP">RTSP</option><option value="V380">V380</option><option value="SIMULATOR">Simulador</option></select>
        </div></div>
          {#if !records.length}<div class="empty"><span class="empty-icon">▣</span><h3>No hay cámaras con estos filtros</h3><p>Registra una cámara o cambia los filtros.</p></div>
          {:else}<div class="camera-grid operational">{#each records as item}<article class="camera-card"><div class="camera-preview"><span>▣</span><p>{item.status === 'ONLINE' ? 'Lista para transmitir' : stateLabel(item.status)}</p><button class="preview-live" disabled={item.status !== 'ONLINE' || item.integration_type === 'SIMULATOR'} onclick={() => openLive(display(item.id), display(item.name))}>▶ Ver en vivo</button></div><div class="camera-caption"><strong>{display(item.name)}</strong><span class="badge">{stateLabel(item.status)}</span><small>{nameOf(tenants, item.tenant_id)} · {nameOf(sites, item.site_id)}</small><a href="/cameras/{item.id}" data-sveltekit-reload>Configuración y detalle →</a></div></article>{/each}</div>{/if}
          <div class="pagination"><span>{totalRecords ? `${(pageNumber - 1) * pageSize + 1}–${Math.min(pageNumber * pageSize, totalRecords)} de ${totalRecords}` : '0 cámaras'}</span><div><button disabled={pageNumber <= 1 || busy} onclick={() => { pageNumber--; void refresh(); }}>← Anterior</button><span>Página {pageNumber} de {totalPages}</span><button disabled={pageNumber >= totalPages || busy} onclick={() => { pageNumber++; void refresh(); }}>Siguiente →</button></div></div>
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
            {#each filtered as row}<tr><td><strong>{display(row.name || row.first_name || row.email || row.action)}</strong>{#if row.integration_type}<small>{row.integration_type === 'SIMULATOR' ? 'Simulador de desarrollo' : 'RTSP'}</small>{/if}</td><td>{section === 'admin/users' ? display(row.email) : section === 'admin/customers' ? display(row.timezone) : section === 'admin/audit' ? display(row.resource_type) : nameOf(tenants, row.tenant_id)}</td><td>{section === 'admin/users' ? roleLabel(row.role) : section === 'admin/audit' ? new Date(display(row.created_at)).toLocaleString('es-PE', {timeZone: 'America/Lima'}) : stateLabel(row.status || row.address || '—')}</td><td>{#if section === 'cameras'}<a href="/cameras/{row.id}" data-sveltekit-reload>Ver detalle →</a>{:else if newPermission() && row.role !== 'SUPER_ADMIN' && row.id !== user?.id}<button class="text-button" onclick={() => openForm(row)}>Editar</button>{:else}—{/if}</td></tr>{/each}
          </tbody></table></div>{/if}
          <div class="pagination"><span>{totalRecords ? `${(pageNumber - 1) * pageSize + 1}–${Math.min(pageNumber * pageSize, totalRecords)} de ${totalRecords}` : '0 registros'}</span><div><button disabled={pageNumber <= 1 || busy} onclick={() => { pageNumber--; void refresh(); }}>← Anterior</button><span>Página {pageNumber} de {totalPages}</span><button disabled={pageNumber >= totalPages || busy} onclick={() => { pageNumber++; void refresh(); }}>Siguiente →</button></div></div>
        </section>
      {:else}<div class="empty"><h2>Página no encontrada</h2><a href="/dashboard" data-sveltekit-reload>Volver al resumen</a></div>{/if}
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
        <label>Sede<select bind:value={siteId} required><option value="">Selecciona una sede</option>{#each sites.filter(s => s.tenant_id === tenantId) as s}<option value={s.id}>{display(s.name)}</option>{/each}</select></label>
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
      {#if ['live', 'reconnecting'].includes(liveStatus) && liveUrl}<WhepPlayer playbackUrl={liveUrl} onState={(state) => { if (state !== 'connecting') liveStatus = state; }} />
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
