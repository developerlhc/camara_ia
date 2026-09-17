import { invoke } from '@tauri-apps/api/core';
import './style.css';
type Row = { id: string; name: string; tenant_id?: string; [key: string]: unknown };
type Scope = { tenant_id: string; site_id: string; tenant_name?: string; site_name?: string };
let selected: Scope | undefined;
let sites: Row[] = [];
let cameras: Row[] = [];
let busy = false;
const byId = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const values = (form: HTMLFormElement) => Object.fromEntries(new FormData(form).entries());
async function operation(label: string, task: () => Promise<unknown>) {
  if (busy) return;
  busy = true;
  document.querySelectorAll<HTMLButtonElement>('button').forEach(b => b.disabled = true);
  byId('status').textContent = label + '… Puede tardar mientras Docker descarga las imágenes.';
  try {
    const result = await task();
    byId('result').textContent = JSON.stringify(result, null, 2) || 'Completado';
    byId('status').textContent = label + ': completado.';
  } catch (error) { byId('status').textContent = String(error); }
  finally { busy = false; document.querySelectorAll<HTMLButtonElement>('button').forEach(b => b.disabled = false); }
}
function scope() {
  if (!selected) throw new Error('Actualiza y selecciona una empresa y sede antes de continuar.');
  return { tenant_id: selected.tenant_id, site_id: selected.site_id };
}
function call(action: string, extra: Record<string, unknown> = {}) {
  return invoke('bridge', { payload: { action, scope: scope(), ...extra } });
}
function option(select: HTMLSelectElement, value: string, label: string) {
  const o = document.createElement('option'); o.value = value; o.textContent = label; select.append(o);
}
function updateSites() {
  const site = byId<HTMLSelectElement>('site'); site.replaceChildren(); option(site, '', 'Crear o buscar por nombre');
  for (const row of sites.filter(s => s.tenant_id === byId<HTMLSelectElement>('tenant').value)) option(site, row.id, row.name);
}
async function catalog() {
  const result = await invoke<{tenants: Row[]; sites: Row[]; configured: Scope | null}>('bridge', {payload: {action: 'catalog'}});
  sites = result.sites;
  selected = result.configured || undefined;
  const tenant = byId<HTMLSelectElement>('tenant'); tenant.replaceChildren(); option(tenant, '', 'Crear o buscar por nombre');
  for (const row of result.tenants) option(tenant, row.id, row.name);
  tenant.value = selected?.tenant_id || ''; updateSites(); byId<HTMLSelectElement>('site').value = selected?.site_id || '';
  byId('scope-badge').textContent = selected ? selected.tenant_name + ' · ' + selected.site_name : 'Selecciona empresa y sede';
  return result;
}
byId('tenant').addEventListener('change', updateSites);
byId('diagnose').onclick = () => void operation('Comprobación', () => invoke('diagnose'));
byId('start-local').onclick = () => void operation('Inicio Local', () => invoke('start_local'));
byId('catalog').onclick = () => void operation('Catálogo', catalog);
byId('prepare').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget as HTMLFormElement; const settings = values(form);
  void operation('Preparación', async () => { const result = await invoke('prepare', {settings}); form.reset(); return result; });
});
byId('scope-form').addEventListener('submit', event => {
  event.preventDefault(); const data = values(event.currentTarget as HTMLFormElement);
  if (!confirm('¿Guardar esta empresa/sede como identidad de la instalación? No se trasladarán cámaras de otras sedes.')) return;
  void operation('Identidad', async () => {
    const result = await invoke<Scope>('bridge', {payload: {action: 'configure_scope', scope: data}});
    selected = result; byId('scope-badge').textContent = result.tenant_name + ' · ' + result.site_name;
    return result;
  });
});
byId('cameras').onclick = () => void operation('Cámaras', async () => {
  cameras = await call('cameras') as Row[];
  const list = byId('camera-list'); list.replaceChildren();
  const select = byId<HTMLSelectElement>('camera-id'); select.replaceChildren(); option(select, '', 'Agregar RTSP');
  for (const row of cameras) {
    const li = document.createElement('li'); li.textContent = row.name + ' · ' + row.integration_type + ' · ' + (row.frigate_camera_name || 'Pendiente de exportar'); list.append(li);
    if (row.integration_type === 'RTSP') option(select, row.id, row.name);
  }
  return cameras;
});
byId('camera-id').onchange = () => {
  const row = cameras.find(c => c.id === byId<HTMLSelectElement>('camera-id').value);
  const form = byId<HTMLFormElement>('camera-form');
  (form.elements.namedItem('name') as HTMLInputElement).value = row?.name || '';
  (form.elements.namedItem('rtsp_url') as HTMLInputElement).value = '';
  (form.elements.namedItem('rtsp_substream_url') as HTMLInputElement).value = '';
};
byId('camera-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
  const camera = values(form);
  void operation('Guardar cámara', async () => { const result = await call('save_camera', {camera}); form.reset(); return result; });
});
for (const name of ['plan', 'export']) byId(name).onclick = () => {
  if (name === 'export' && !confirm('¿Exportar las cámaras de esta sede? Sólo se actualizará la configuración administrada por Desktop.')) return;
  void operation(name === 'plan' ? 'Plan de instalación' : 'Exportación', () => call(name, {days: Number(byId<HTMLInputElement>('days').value)}));
};
byId('start-frigate').onclick = () => {
  if (confirm('Se descargará e iniciará Frigate de Desktop. Al aplicar cambios se reinicia sólo esa instancia. ¿Continuar?')) void operation('Instalación Frigate', () => invoke('start_frigate'));
};
byId('bind').onclick = () => void operation('Verificación y vinculación', () => call('bind'));
byId('gateway').onclick = () => {
  if (confirm('¿Activar el túnel autenticado de esta sede para que Vigilay Web consulte sus eventos y grabaciones? Sustituirá la conexión Frigate registrada para esta sede.')) void operation('Gateway', () => invoke('connect_gateway'));
};
byId('generate').onclick = () => {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  byId<HTMLInputElement>('frigate-password').value = Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
  byId('status').textContent = 'Contraseña generada. Guárdala antes de establecerla: no se conservará en Desktop.';
};
byId('show-password').onchange = () => { byId<HTMLInputElement>('frigate-password').type = byId<HTMLInputElement>('show-password').checked ? 'text' : 'password'; };
byId('password-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!confirm('¿Establecer esta contraseña para admin en el Frigate administrado por Desktop?')) return;
  void operation('Contraseña Frigate', async () => { const result = await call('password', {password: byId<HTMLInputElement>('frigate-password').value}); byId<HTMLInputElement>('frigate-password').value = ''; return result; });
});
document.querySelectorAll<HTMLButtonElement>('[data-open]').forEach(button => { button.onclick = () => void operation('Abrir', () => invoke('open_page', {page: button.dataset.open})); });
