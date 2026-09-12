<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { api, setCsrf, type Me, type Row } from '$lib/api';

  const titles: Record<string, string> = { dashboard: 'Resumen general', 'admin/customers': 'Clientes', 'admin/sites': 'Sedes', 'admin/users': 'Usuarios', cameras: 'Cámaras', 'admin/audit': 'Auditoría', 'admin/system': 'Estado del sistema', profile: 'Mi perfil' };
  const endpoints: Record<string, string> = { 'admin/customers': '/tenants', 'admin/sites': '/sites', 'admin/users': '/users', cameras: '/cameras', 'admin/audit': '/audit' };
  let section = $derived(page.params.section || 'dashboard');
  let cameraId = $derived(section.startsWith('cameras/') ? section.split('/')[1] : '');
  let title = $derived(cameraId ? 'Detalle de cámara' : titles[section] || 'Página no encontrada');
  let user = $state<Me | null>(null); let loading = $state(true); let busy = $state(false);
  let error = $state(''); let notice = $state(''); let records = $state<Row[]>([]);
  let tenants = $state<Row[]>([]); let sites = $state<Row[]>([]); let users = $state<Row[]>([]);
  let metrics = $state<Record<string, number>>({}); let health = $state<Record<string, string>>({});
  let camera = $state<Row | null>(null); let capabilities = $state<Row[]>([]); let settings = $state<Row[]>([]); let commands = $state<Row[]>([]);
  let showForm = $state(false); let editing = $state(''); let search = $state('');
  let name = $state(''); let tenantId = $state(''); let siteId = $state(''); let address = $state('');
  let email = $state(''); let username = $state(''); let password = $state(''); let firstName = $state(''); let lastName = $state(''); let role = $state('VIEWER'); let status = $state('ACTIVE');
  let integration = $state('SIMULATOR'); let rtspUrl = $state(''); let sensitivity = $state(50);
  let grantedUser = $state(''); let canView = $state(true); let canConfigure = $state(false);
  let currentPassword = $state(''); let newPassword = $state('');
  let filtered = $derived(records.filter(r => JSON.stringify(r).toLowerCase().includes(search.toLowerCase())));
  const display = (value: unknown) => value === null || value === undefined ? '—' : String(value);
  const nameOf = (rows: Row[], id: unknown) => display(rows.find(r => r.id === id)?.name || '—');
  const can = (key: string) => user?.permissions.includes(key) || false;
  const stateLabel = (value: unknown) => ({ ACTIVE: 'Activo', SUSPENDED: 'Suspendido', DISABLED: 'Deshabilitado', ONLINE: 'En línea', OFFLINE: 'Sin conexión', UNVERIFIED: 'Sin verificar', SYNCED: 'Sincronizado', DRIFTED: 'Configuración diferente', PENDING: 'Pendiente', RUNNING: 'Ejecutando', SUCCEEDED: 'Completado', FAILED: 'Falló', ERROR: 'Error' }[String(value)] || display(value));
  const roleLabel = (value: unknown) => ({ SUPER_ADMIN: 'Superadministrador', CLIENT_ADMIN: 'Administrador de cliente', OPERATOR: 'Operador', VIEWER: 'Observador' }[String(value)] || display(value));

  async function refresh() {
    error = '';
    if (cameraId) {
      camera = await api<Row>(`/cameras/${cameraId}`);
      capabilities = await api(`/cameras/${cameraId}/capabilities`);
      if (can('cameras.configure')) {
        settings = await api(`/cameras/${cameraId}/settings`);
        commands = await api(`/cameras/${cameraId}/commands`);
      }
    } else if (section === 'dashboard') {
      metrics = await api<Record<string, number>>('/dashboard'); records = await api('/cameras');
    } else if (section === 'admin/system') health = await api<Record<string, string>>('/system/health');
    else if (endpoints[section]) records = await api(endpoints[section]);
  }
  onMount(() => {
    let timer: ReturnType<typeof setInterval>;
    void (async () => {
      try {
        user = await api<Me>('/me'); setCsrf(user.csrf_token);
        [tenants, sites] = await Promise.all([api('/tenants'), api('/sites')]);
        tenantId = user.tenant_id || tenants[0]?.id || '';
        if (cameraId && can('users.manage')) users = await api('/users');
        await refresh();
        if (cameraId) timer = setInterval(() => { void refresh().catch(e => error = e.message); }, 3000);
      } catch(e) { error = (e as Error).message; } finally { loading = false; }
    })();
    return () => clearInterval(timer);
  });

  async function action(work: () => Promise<unknown>, message: string) {
    busy = true; error = ''; notice = '';
    try { await work(); notice = message; await refresh(); }
    catch(e) { error = (e as Error).message; } finally { busy = false; }
  }
  function openForm(row?: Row) {
    editing = row?.id || ''; name = display(row?.name || ''); address = display(row?.address || '');
    email = display(row?.email || ''); username = display(row?.username || ''); password = '';
    firstName = display(row?.first_name || ''); lastName = display(row?.last_name || '');
    role = display(row?.role || 'VIEWER'); status = display(row?.status || 'ACTIVE');
    tenantId = display(row?.tenant_id || user?.tenant_id || tenants[0]?.id || '');
    siteId = ''; rtspUrl = ''; showForm = true;
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
      } else if (section === 'cameras') data = { name, tenant_id: tenantId, site_id: siteId, integration_type: integration, ...(integration === 'RTSP' ? { rtsp_url: rtspUrl } : {}) };
      await api(endpoints[section] + (editing ? `/${editing}` : ''), editing ? 'PUT' : 'POST', data);
      showForm = false; password = ''; rtspUrl = '';
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
          {:else}<div class="camera-grid">{#each records as item}<a href="/cameras/{item.id}" class="camera-card" data-sveltekit-reload><div class="camera-preview"><span>▣</span><p>{item.integration_type === 'SIMULATOR' ? 'Simulador de desarrollo' : 'Vista en vivo pendiente de Edge Agent'}</p></div><div class="camera-caption"><strong>{display(item.name)}</strong><span class="badge">{stateLabel(item.status)}</span><small>{nameOf(sites, item.site_id)}</small></div></a>{/each}</div>{/if}
        </section>
      {:else if cameraId && camera}
        <div class="detail-title"><h2>{display(camera.name)}</h2><span class="badge">{stateLabel(camera.status)}</span><span class="badge">{camera.integration_type === 'SIMULATOR' ? 'Simulador' : 'RTSP'}</span></div>
        <p class="message">{camera.integration_type === 'SIMULATOR' ? 'Este dispositivo simula configuración y conectividad. No genera video ni detecciones de personas.' : 'Cámara registrada. El video y la conexión RTSP se habilitarán al integrar el Edge Agent.'}</p>
        {#if can('cameras.configure')}
          <section class="panel"><div class="panel-heading"><h2>Capacidades y configuración</h2><button disabled={busy} onclick={() => action(() => api(`/cameras/${cameraId}/probe`, 'POST'), 'Prueba encolada. Esperando al worker…')}>Probar conexión</button></div>
            {#if !capabilities.length}<div class="empty"><p>Aún no se han detectado capacidades. Ejecuta una prueba de conexión.</p></div>{/if}
            {#each capabilities as cap}{#if cap.key === 'motion_sensitivity' && cap.writable}
              <form class="settings-form" onsubmit={(e) => { e.preventDefault(); void action(() => api(`/cameras/${cameraId}/settings`, 'PUT', { motion_sensitivity: sensitivity }), 'Configuración encolada. Se verificará leyendo el dispositivo.'); }}>
                <label>Sensibilidad de movimiento (0–100)<input type="number" min="0" max="100" bind:value={sensitivity} required /></label><button class="primary" disabled={busy}>Aplicar configuración</button>
              </form>{/if}{/each}
            {#each settings as setting}<div class="setting-row"><strong>Sensibilidad de movimiento</strong><span>Deseado: {display(setting.desired)}</span><span>Reportado: {display(setting.reported)}</span><span class="badge">{stateLabel(setting.status)}</span></div>{/each}
          </section>
          <section class="panel"><div class="panel-heading"><h2>Historial de comandos</h2><small>Actualización cada 3 segundos</small></div><div class="table-wrap"><table><thead><tr><th>Comando</th><th>Estado</th><th>Fecha</th><th>Resultado</th></tr></thead><tbody>{#each commands as c}<tr><td>{c.command === 'PROBE' ? 'Probar conexión' : 'Aplicar configuración'}</td><td>{stateLabel(c.status)}</td><td>{new Date(display(c.created_at)).toLocaleString('es-PE', {timeZone: 'America/Lima'})}</td><td>{display(c.error)}</td></tr>{/each}</tbody></table></div></section>
        {/if}
        {#if can('cameras.manage')}<section class="panel"><div class="panel-heading"><h2>Acceso por usuario</h2></div><form class="settings-form" onsubmit={(e) => {e.preventDefault(); void action(() => api(`/cameras/${cameraId}/permissions`, 'PUT', {user_id: grantedUser, can_view: canView, can_configure: canConfigure}), 'Permisos guardados.');}}>
          <label>Usuario<select bind:value={grantedUser} required><option value="">Selecciona un usuario</option>{#each users.filter(u => u.tenant_id === camera?.tenant_id) as u}<option value={u.id}>{display(u.email)}</option>{/each}</select></label>
          <label class="check"><input type="checkbox" bind:checked={canView} /> Ver cámara</label><label class="check"><input type="checkbox" bind:checked={canConfigure} /> Configurar cámara</label><button disabled={busy}>Guardar permisos</button>
        </form></section>{/if}
      {:else if section === 'admin/system'}
        <section class="panel"><div class="panel-heading"><h2>Servicios</h2><button onclick={() => action(refresh, 'Estado actualizado.')} disabled={busy}>Actualizar</button></div>{#each Object.entries(health) as [service, value]}<div class="setting-row"><strong>{service === 'media' ? 'Video en vivo' : service.toUpperCase()}</strong><span class="badge">{value === 'ok' ? 'Operativo' : value === 'offline' ? 'Sin conexión' : 'Pendiente de integración'}</span></div>{/each}</section>
      {:else if section === 'profile'}
        <section class="panel profile"><h2>{user?.first_name}</h2><p>{user?.email}</p><p>{roleLabel(user?.role)}</p><h3>Cambiar contraseña</h3>
          <form onsubmit={(e) => {e.preventDefault(); void action(async () => {await api('/auth/change-password', 'POST', {current_password: currentPassword, new_password: newPassword}); location.assign('/login');}, 'Contraseña actualizada.');}}>
            <label>Contraseña actual<input type="password" autocomplete="current-password" bind:value={currentPassword} required /></label><label>Nueva contraseña<input type="password" autocomplete="new-password" minlength="12" bind:value={newPassword} required /></label><button class="primary" disabled={busy}>Cambiar y cerrar las sesiones</button>
          </form>
        </section>
      {:else if endpoints[section]}
        <section class="panel"><div class="panel-heading"><h2>{titles[section]} <span class="count">{records.length}</span></h2><input aria-label="Buscar registros" type="search" placeholder="Buscar en los registros cargados…" bind:value={search} /></div>
          {#if !filtered.length}<div class="empty"><span class="empty-icon">▦</span><h3>{records.length ? 'Sin coincidencias' : 'Todavía no hay registros'}</h3><p>{records.length ? 'Prueba con otro término de búsqueda.' : 'Los registros que crees aparecerán aquí.'}</p></div>
          {:else}<div class="table-wrap"><table><thead><tr><th>{section === 'admin/audit' ? 'Acción' : 'Nombre'}</th><th>{section === 'admin/users' ? 'Correo' : section === 'admin/audit' ? 'Recurso' : 'Cliente / detalle'}</th><th>{section === 'admin/users' ? 'Rol' : section === 'admin/audit' ? 'Fecha' : 'Estado / ubicación'}</th><th>Acciones</th></tr></thead><tbody>
            {#each filtered as row}<tr><td><strong>{display(row.name || row.first_name || row.email || row.action)}</strong>{#if row.integration_type}<small>{row.integration_type === 'SIMULATOR' ? 'Simulador de desarrollo' : 'RTSP'}</small>{/if}</td><td>{section === 'admin/users' ? display(row.email) : section === 'admin/customers' ? display(row.timezone) : section === 'admin/audit' ? display(row.resource_type) : nameOf(tenants, row.tenant_id)}</td><td>{section === 'admin/users' ? roleLabel(row.role) : section === 'admin/audit' ? new Date(display(row.created_at)).toLocaleString('es-PE', {timeZone: 'America/Lima'}) : stateLabel(row.status || row.address || '—')}</td><td>{#if section === 'cameras'}<a href="/cameras/{row.id}" data-sveltekit-reload>Ver detalle →</a>{:else if newPermission() && row.role !== 'SUPER_ADMIN' && row.id !== user?.id}<button class="text-button" onclick={() => openForm(row)}>Editar</button>{:else}—{/if}</td></tr>{/each}
          </tbody></table></div>{/if}
        </section>
        <p class="muted footnote">Se muestran hasta 100 registros por consulta.</p>
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
      {:else}<label>Nombre<input bind:value={name} required maxlength="160" /></label>{/if}
      {#if editing && (section === 'admin/customers' || section === 'admin/users')}<label>Estado<select bind:value={status}><option value="ACTIVE">Activo</option><option value={section === 'admin/users' ? 'DISABLED' : 'SUSPENDED'}>{section === 'admin/users' ? 'Deshabilitado' : 'Suspendido'}</option></select></label>{/if}
      {#if section === 'admin/sites'}<label>Dirección<input bind:value={address} maxlength="300" /></label>{/if}
      {#if section === 'cameras'}
        <label>Sede<select bind:value={siteId} required><option value="">Selecciona una sede</option>{#each sites.filter(s => s.tenant_id === tenantId) as s}<option value={s.id}>{display(s.name)}</option>{/each}</select></label>
        <label>Método de integración<select bind:value={integration}><option value="SIMULATOR">Simulador de desarrollo</option><option value="RTSP">RTSP — registrar conexión</option></select></label>
        {#if integration === 'RTSP'}<label>URL RTSP<input type="password" bind:value={rtspUrl} required autocomplete="off" placeholder="rtsp://usuario:clave@direccion/ruta" /></label><p class="muted">Se guardará cifrada. La prueba de conexión y el video requieren la futura integración del Edge Agent.</p>{:else}<p class="muted">Permite probar comandos y configuración sin conectar una cámara física.</p>{/if}
      {/if}
      {#if error}<p class="message error" role="alert">{error}</p>{/if}
      <div class="form-actions"><button type="button" onclick={() => showForm = false}>Cancelar</button><button class="primary" disabled={busy}>{busy ? 'Guardando…' : 'Guardar'}</button></div>
    </form>
  </dialog>
{/if}
