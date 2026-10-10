import { expect, test } from '@playwright/test';

// File operations use directory file descriptors that only exist on Linux,
// which is where Titan runs and where CI executes this suite.
const linuxOnly = process.platform === 'win32';

test('start page shows system tiles and installed apps', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('demo');
  await expect(page.getByText('CPU', { exact: true })).toBeVisible();
  await expect(page.getByText('RAM', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Syncthing öffnen' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Hauptnavigation' }).getByRole('button')).toHaveCount(5);
});

test('an app can be stopped and started from its menu', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Aktionen für Syncthing' }).click();
  await page.getByRole('menuitem', { name: 'Stoppen' }).click();
  await expect(page.getByText('Syncthing: gestoppt.')).toBeVisible();
  await page.getByRole('button', { name: 'Aktionen für Syncthing' }).click();
  await expect(page.getByRole('menuitem', { name: 'Stoppen' })).toHaveCount(0);
  await page.getByRole('menuitem', { name: 'Starten' }).click();
  await expect(page.getByText('Syncthing: gestartet.')).toBeVisible();
});

test('app store lists, filters and opens an app', async ({ page }) => {
  await page.goto('/#/store');
  await expect(page.getByRole('heading', { name: 'App Store' })).toBeVisible();
  await page.getByRole('textbox', { name: 'Apps suchen' }).fill('adguard');
  await expect(page.getByRole('button', { name: /AdGuard Home/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Jellyfin/ })).toHaveCount(0);
  await page.getByRole('button', { name: /AdGuard Home/ }).click();
  await expect(page).toHaveURL(/#\/store\/titan-adguard$/);
  await expect(page.getByRole('heading', { name: 'AdGuard Home' })).toBeVisible();
  // The demo never installs; the button must say so instead of failing later.
  await expect(page.getByRole('button', { name: 'Installieren' })).toBeDisabled();
  await page.getByRole('button', { name: 'App Store' }).first().click();
  await expect(page).toHaveURL(/#\/store$/);
});

test('virtual machines can be created and controlled', async ({ page }) => {
  await page.goto('/#/vms');
  await expect(page.getByText('linux-lab')).toBeVisible();
  await page.getByRole('button', { name: 'Neue VM' }).click();
  const dialog = page.getByRole('dialog', { name: 'Neue virtuelle Maschine' });
  await dialog.getByLabel('Name').fill('E2E Gast');
  await dialog.getByRole('button', { name: 'Anlegen' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('E2E Gast').first()).toBeVisible();
  await page.keyboard.press('Escape');
});

test('an uploaded ISO becomes a boot source for new VMs', async ({ page }) => {
  await page.goto('/#/vms');
  await page.locator('input[type=file]').setInputFiles({ name: 'e2e-installer.iso', mimeType: 'application/octet-stream', buffer: Buffer.alloc(3 * 1024 * 1024 + 17, 7) });
  await expect(page.getByText('e2e-installer.iso steht als Startmedium bereit.')).toBeVisible();
  await page.getByRole('button', { name: 'Neue VM' }).click();
  await expect(page.getByRole('dialog').getByRole('option', { name: 'e2e-installer.iso' })).toBeAttached();
});

test('settings sections load their data', async ({ page }) => {
  await page.goto('/#/settings');
  await expect(page.getByText('Laufzeit')).toBeVisible();
  await page.getByRole('button', { name: 'Speicher' }).click();
  await expect(page.getByText('tank')).toBeVisible();
  await page.getByRole('button', { name: 'Benutzer' }).click();
  await expect(page.getByText('Administrator').first()).toBeVisible();
  await page.getByRole('button', { name: 'Updates' }).click();
  await expect(page.getByText(/Titan ist aktuell|ist verfügbar/)).toBeVisible();
});

test('a share can be created and removed', async ({ page }) => {
  await page.goto('/#/settings/shares');
  await expect(page.getByText('dokumente', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Neue Freigabe' }).click();
  const dialog = page.getByRole('dialog', { name: 'Neue Freigabe' });
  await dialog.getByLabel('Name').fill('e2e-freigabe');
  await dialog.getByLabel('Zugriff für patrick').selectOption('write');
  await dialog.getByRole('button', { name: 'Anlegen' }).click();
  await expect(page.getByText('e2e-freigabe', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Freigabe e2e-freigabe entfernen' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Entfernen' }).click();
  await expect(page.getByText('e2e-freigabe', { exact: true })).toHaveCount(0);
});

test('previous interface stays reachable', async ({ request }) => {
  const response = await request.get('/classic');
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain('/app.js');
});

test('files can be uploaded, downloaded, renamed and moved to the trash', async ({ page }) => {
  test.skip(linuxOnly, 'file API needs Linux');
  const folder = `e2e-${Date.now()}`;
  const content = 'Titan Ende-zu-Ende ✓\n'.repeat(2000);
  await page.goto('/#/files');
  await expect(page.getByRole('button', { name: 'dokumente' }).first()).toBeVisible();

  await page.getByRole('button', { name: 'Neuer Ordner' }).click();
  await page.getByRole('dialog').getByLabel('Ordnername').fill(folder);
  await page.getByRole('dialog').getByRole('button', { name: 'Anlegen' }).click();
  await page.getByRole('button', { name: folder, exact: true }).click();
  await expect(page.getByText('Dieser Ordner ist leer')).toBeVisible();

  await page.locator('input[type=file]').setInputFiles({ name: 'notiz.txt', mimeType: 'text/plain', buffer: Buffer.from(content) });
  await expect(page.getByText('notiz.txt hochgeladen.')).toBeVisible();
  await expect(page.getByText('notiz.txt', { exact: true })).toBeVisible();

  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'notiz.txt herunterladen' }).click()]);
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(chunk as Buffer);
  expect(Buffer.concat(chunks).toString()).toBe(content);

  await page.getByRole('button', { name: 'notiz.txt umbenennen' }).click();
  await page.getByRole('dialog').getByLabel('Neuer Name').fill('umbenannt.txt');
  await page.getByRole('dialog').getByRole('button', { name: 'Umbenennen' }).click();
  await expect(page.getByText('umbenannt.txt', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'umbenannt.txt in den Papierkorb' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Verschieben' }).click();
  await expect(page.getByText('Dieser Ordner ist leer')).toBeVisible();
});
