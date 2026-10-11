import { expect, test } from '@playwright/test';

test('human share names open the selected folder and accept large and empty files', async ({ page }) => {
  test.skip(process.platform === 'win32', 'File worker requires Linux.');
  await page.goto('/#/settings/shares');
  await page.getByRole('button', { name: 'Neue Freigabe' }).click();
  const dialog = page.getByRole('dialog', { name: 'Neue Freigabe' });
  await dialog.getByPlaceholder('Meine Dateien').fill('Meine Dateien für Jörg');
  await dialog.getByLabel('Zugriff für patrick').selectOption('write');
  await dialog.getByRole('button', { name: 'Anlegen' }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole('listitem').filter({ has: page.getByText('Meine Dateien für Jörg', { exact: true }) }).getByRole('button', { name: 'Öffnen' }).click();
  await expect(page.getByRole('navigation', { name: 'Pfad' })).toContainText('Meine Dateien für Jörg');
  const offsets: number[] = [];
  page.on('request', request => {
    if (request.url().endsWith('/api/file-upload')) offsets.push(JSON.parse(decodeURIComponent(request.headers()['x-titan-upload'])).offset);
  });
  await page.locator('input[type=file]').setInputFiles([
    { name: 'groß.bin', mimeType: 'application/octet-stream', buffer: Buffer.alloc(8 * 1024 * 1024 + 19, 7) },
    { name: 'leer.txt', mimeType: 'text/plain', buffer: Buffer.alloc(0) },
  ]);
  await expect(page.getByText('leer.txt', { exact: true })).toBeVisible();
  await expect(page.getByText('groß.bin', { exact: true })).toBeVisible();
  expect(offsets).toEqual([0, 8 * 1024 * 1024, 0]);
  const share = decodeURIComponent(new URL(page.url()).hash.split('/').pop()!);
  const download = await page.request.get('/api/file?' + new URLSearchParams({ share, path: 'groß.bin' }));
  expect(download.ok()).toBe(true);
  expect(await download.body()).toEqual(Buffer.alloc(8 * 1024 * 1024 + 19, 7));
});

test('remote settings show the actual origin and run a diagnosis without leaving Titan', async ({ page }) => {
  await page.route('**/api/remote-access', route => route.fulfill({ json: {
    remote: { enabled: true, public_origin: 'https://nas.example.com', connector: 'titan-cloudflared', app_urls: {}, service_url: 'http://127.0.0.1:5102' },
    revision: 'test', connectors: [{ id: 'titan-cloudflared', name: 'Cloudflare Tunnel' }], apps: [],
  } }));
  await page.route('**/api/remote-access/diagnose', route => route.fulfill({ json: {
    connected: false, message: 'Leere Antwort', checks: [{ name: 'Öffentliche HTTPS-Adresse', ok: false, message: 'Die Domain antwortet leer (HTTP 200, 0 Bytes).' }],
  } }));
  await page.goto('/#/settings/remote');
  await expect(page.getByLabel('Tunnel-Zieladresse')).toHaveValue('http://127.0.0.1:5102');
  await page.getByRole('button', { name: 'Verbindung prüfen' }).click();
  await expect(page.getByText(/Die Domain antwortet leer/)).toBeVisible();
  await expect(page).toHaveURL(/#\/settings\/remote$/);
});
