import { test, expect } from '@playwright/test';

const email = process.env.VIGILAY_E2E_EMAIL;
const password = process.env.VIGILAY_E2E_PASSWORD;

test('login, cliente, sede, usuario, cámara, readback y logout', async ({ page }) => {
  test.skip(!email || !password, 'Define VIGILAY_E2E_EMAIL y VIGILAY_E2E_PASSWORD con una cuenta de desarrollo.');
  const stamp = Date.now();
  const customer = `Demostración ${stamp}`;
  const site = `Sede de prueba ${stamp}`;
  const camera = `Entrada simulada ${stamp}`;
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));

  await page.goto('/login');
  await page.getByLabel('Correo o usuario').fill(email!);
  await page.getByLabel('Contraseña', { exact: true }).fill(password!);
  await page.getByRole('button', { name: 'Ingresar a Vigilay' }).click();
  await expect(page.getByRole('heading', { name: 'Resumen general' })).toBeVisible();
  await page.getByRole('link', { name: 'Clientes', exact: false }).click();
  await page.getByRole('button', { name: 'Crear registro' }).click();
  await page.getByLabel('Nombre', { exact: true }).fill(customer);
  await page.getByRole('button', { name: 'Guardar', exact: true }).click();
  await expect(page.getByRole('cell', { name: customer, exact: true })).toBeVisible();

  await page.getByRole('link', { name: 'Sedes', exact: false }).click();
  await page.getByRole('button', { name: 'Crear registro' }).click();
  await page.getByRole('combobox', { name: 'Cliente', exact: true }).selectOption({ label: customer });
  await page.getByLabel('Nombre', { exact: true }).fill(site);
  await page.getByLabel('Dirección').fill('Sede de demostración, Lima');
  await page.getByRole('button', { name: 'Guardar', exact: true }).click();
  await expect(page.getByRole('cell', { name: site, exact: true })).toBeVisible();

  await page.getByRole('link', { name: 'Usuarios', exact: false }).click();
  await page.getByRole('button', { name: 'Crear registro' }).click();
  await page.getByRole('combobox', { name: 'Cliente', exact: true }).selectOption({ label: customer });
  await page.getByLabel('Correo', { exact: true }).fill(`demo-${stamp}@example.com`);
  await page.getByLabel('Usuario', { exact: true }).fill(`demo-${stamp}`);
  await page.getByLabel('Contraseña inicial').fill(`Demo-test-${stamp}-only!`);
  await page.getByLabel('Nombres', { exact: true }).fill('Administrador de prueba');
  await page.getByRole('combobox', { name: 'Rol', exact: true }).selectOption('CLIENT_ADMIN');
  await page.getByRole('button', { name: 'Guardar', exact: true }).click();
  await expect(page.getByRole('cell', { name: `demo-${stamp}@example.com`, exact: true })).toBeVisible();

  await page.getByRole('link', { name: 'Cámaras', exact: false }).click();
  await page.getByRole('button', { name: 'Agregar cámara' }).click();
  await page.getByRole('combobox', { name: 'Cliente', exact: true }).selectOption({ label: customer });
  await page.getByLabel('Nombre', { exact: true }).fill(camera);
  await page.getByRole('combobox', { name: 'Sede', exact: true }).selectOption({ label: site });
  await page.getByRole('button', { name: 'Guardar', exact: true }).click();
  const cameraRow = page.getByRole('row').filter({ hasText: camera });
  await expect(cameraRow).toBeVisible();
  await cameraRow.getByRole('link', { name: 'Ver detalle' }).click();
  await page.getByRole('button', { name: 'Probar conexión' }).click();
  await expect(page.getByLabel('Sensibilidad de movimiento (0–100)')).toBeVisible();
  await page.getByLabel('Sensibilidad de movimiento (0–100)').fill('70');
  await page.getByRole('button', { name: 'Aplicar configuración' }).click();
  await expect(page.getByText('Reportado: 70', { exact: true })).toBeVisible();
  await expect(page.getByText('Sincronizado', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/camera-settings.png', fullPage: true });
  await page.getByRole('link', { name: 'Resumen general', exact: false }).click();
  await expect(page.getByText(camera, { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/dashboard.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'Resumen general' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/mobile-dashboard.png', fullPage: true });
  await page.getByRole('button', { name: 'Cerrar sesión' }).click();
  await expect(page.getByRole('heading', { name: 'Inicia sesión' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('acceso anónimo redirige al login', async ({ page }) => {
  await page.goto('/cameras');
  await expect(page).toHaveURL(/\/login$/);
});
