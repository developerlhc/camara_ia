import { test, expect, type Page } from '@playwright/test';

async function mockApi(page: Page, delayedStart = false) {
  const starts: string[] = [], stops: string[] = [], queries: URL[] = [];
  const companies = [{id: 'a', name: 'Cenfelec'}, {id: 'b', name: 'Otra empresa'}];
  const sites = [{id: 'sa', tenant_id: 'a', name: 'Sede principal'}, {id: 'sb', tenant_id: 'b', name: 'Otra sede'}];
  const cameras = ['1', '2', '3', '4'].map(id => ({id, name: `Cámara ${id}`, tenant_id: 'a', site_id: 'sa', integration_type: 'RTSP', enabled: true, status: 'ONLINE', frigate_camera_name: `cam${id}`}));
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()); queries.push(url);
    const path = url.pathname.replace('/api/v1', '');
    let data: unknown = [];
    if (path === '/me') data = {id: 'admin', tenant_id: null, first_name: 'Admin', role: 'SUPER_ADMIN', permissions: ['cameras.read'], csrf_token: 'fake'};
    else if (path === '/tenants') data = companies;
    else if (path === '/sites') data = sites;
    else if (path === '/cameras') {
      const rows = url.searchParams.get('tenant_id') === 'b' ? [] : cameras;
      data = url.searchParams.has('paged') ? {items: rows, total: rows.length, pages: 1} : rows;
    } else if (path.endsWith('/live/start')) {
      starts.push(path);
      if (delayedStart) await new Promise(resolve => setTimeout(resolve, 1500));
      data = {sessionId: path, viewerKey: 'fake', playbackUrl: 'https://whep.example/play', status: 'starting'};
    } else if (path.endsWith('/live/stop')) { stops.push(path); data = {status: 'stopped'}; }
    else if (path.endsWith('/live/heartbeat')) data = {status: 'live'};
    else if (path === '/frigate/recordings') data = [
      {start: 200, end: 210, duration: 10, camera_name: 'Cámara 1', clip_url: '/api/v1/frigate/newer.mp4'},
      {start: 100, end: 110, duration: 10, camera_name: 'Cámara 1', clip_url: '/api/v1/frigate/older.mp4'},
    ];
    await route.fulfill({json: data});
  });
  await page.route('https://whep.example/**', route => route.fulfill({status: 201, body: 'fake-sdp', headers: {location: '/session', 'content-type': 'application/sdp'}}));
  // Exercise lifecycle without touching physical cameras or incurring provider usage.
  await page.addInitScript(() => {
    class Peer {
      connectionState = 'new';
      ontrack: ((event: {track: MediaStreamTrack}) => void) | null = null;
      onconnectionstatechange: (() => void) | null = null;
      addTransceiver() {}
      async createOffer() { return {type: 'offer', sdp: 'fake-offer'}; }
      async setLocalDescription() {}
      async setRemoteDescription() { this.connectionState = 'connected'; this.onconnectionstatechange?.(); }
      close() { this.connectionState = 'closed'; }
    }
    Object.defineProperty(window, 'RTCPeerConnection', {value: Peer});
  });
  return {starts, stops, queries};
}

test('automatic scoped live, bounded page and cleanup on company change', async ({page}) => {
  await page.setViewportSize({width: 1600, height: 1600});
  const mock = await mockApi(page);
  await page.goto('/cameras');
  await expect(page.getByLabel('Empresa de las cámaras')).toHaveValue('a');
  await expect(page.getByLabel('Sede de las cámaras')).toHaveValue('sa');
  await expect.poll(() => mock.starts.length).toBe(4);
  const query = mock.queries.find(url => url.searchParams.has('paged'))!;
  expect(query.searchParams.get('tenant_id')).toBe('a');
  expect(query.searchParams.get('site_id')).toBe('sa');
  expect(query.searchParams.get('page_size')).toBe('4');
  // Transport connected with no decoded frame must never claim video is live.
  await expect(page.getByRole('status').filter({hasText: /^En vivo$/})).toHaveCount(0);
  await page.getByLabel('Empresa de las cámaras').selectOption('b');
  await expect(page.getByLabel('Sede de las cámaras')).toHaveValue('sb');
  await expect.poll(() => mock.stops.length).toBe(4);
  await expect(page.locator('video')).toHaveCount(0);
});

test('late starts are stopped after navigation; queued requests are cancelled', async ({page}) => {
  await page.setViewportSize({width: 1600, height: 1600});
  const mock = await mockApi(page, true);
  await page.goto('/cameras');
  await expect.poll(() => mock.starts.length).toBe(2);
  await page.getByRole('link', {name: 'Grabaciones', exact: false}).click();
  await expect.poll(() => mock.stops.length).toBe(2);
  expect(mock.starts.length).toBe(2);
});

test('recording dates, download link and forward continuous playback', async ({page}) => {
  const mock = await mockApi(page);
  await page.goto('/recordings');
  await page.getByLabel('Desde (fecha y hora local)').fill('2026-09-10T10:00');
  await page.getByLabel('Hasta (fecha y hora local)').fill('2026-09-10T11:00');
  await page.getByRole('button', {name: 'Aplicar intervalo'}).click();
  await expect.poll(() => mock.queries.filter(url => url.pathname.endsWith('/recordings')).length).toBe(2);
  const last = mock.queries.filter(url => url.pathname.endsWith('/recordings')).at(-1)!;
  expect(Number(last.searchParams.get('before')) - Number(last.searchParams.get('after'))).toBe(3600);
  await expect(page.getByTitle('Descargar grabación').first()).toHaveAttribute('href', /download=true/);
  await page.getByRole('button', {name: 'Reproducir continuo'}).last().click();
  await expect(page.locator('video')).toHaveAttribute('src', /older.mp4/);
  await page.locator('video').dispatchEvent('ended');
  await expect(page.locator('video')).toHaveAttribute('src', /newer.mp4/);
});

test('unreachable recording storage is an error, not an empty collection', async ({page}) => {
  await mockApi(page);
  await page.route('**/api/v1/frigate/recordings?**', route => route.fulfill({status: 502, json: {detail: 'Enlace desconectado'}}));
  await page.goto('/recordings');
  await expect(page.getByRole('alert')).toContainText('Enlace desconectado');
  await expect(page.getByText('No hay grabaciones en el intervalo seleccionado')).toHaveCount(0);
});
