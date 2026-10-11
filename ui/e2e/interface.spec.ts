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

test('Immich install form offers storage, port and a RAM check', async ({ page }) => {
  await page.goto('/#/store/titan-immich');
  await expect(page.getByRole('heading', { name: 'Immich' })).toBeVisible();
  await expect(page.getByLabel('Speicherort')).toBeVisible();
  await expect(page.getByLabel('Port')).toHaveValue('2283');
  await expect(page.getByLabel('RAM-Profil').getByRole('option')).toHaveCount(2);
  // The demo host has 8 GiB; the full Immich stack does not fit and must say so up front.
  await expect(page.getByText(/Zu wenig freier Arbeitsspeicher/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Installieren' })).toBeDisabled();
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

test('an installed app has a detail page with log and controls', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Aktionen für Syncthing' }).click();
  await page.getByRole('menuitem', { name: 'Details und Protokoll' }).click();
  await expect(page).toHaveURL(/#\/apps\/syncthing$/);
  await expect(page.getByRole('heading', { name: 'Syncthing' })).toBeVisible();
  await expect(page.getByLabel('Protokoll der App')).toContainText('Demo');
  await page.getByRole('button', { name: 'Neu starten' }).click();
  await expect(page.getByText('Syncthing: neu gestartet.')).toBeVisible();
});

test('device passthrough is offered for apps and virtual machines', async ({ page }) => {
  await page.goto('/#/apps/syncthing');
  await expect(page.getByRole('heading', { name: 'Grafikkarte und Geräte' })).toBeVisible();
  // The demo host has no passthrough devices; the card must say so instead of staying empty.
  await expect(page.getByText(/keine Grafikkarte und kein USB-Gerät gefunden/)).toBeVisible();

  await page.goto('/#/vms');
  await page.getByRole('button', { name: 'Weitere Aktionen für linux-lab' }).click();
  await page.getByRole('menuitem', { name: 'USB-Geräte' }).click();
  const dialog = page.getByRole('dialog', { name: /USB-Geräte für/ });
  await expect(dialog.getByText(/kein USB-Gerät angeschlossen/)).toBeVisible();
  await dialog.getByRole('button', { name: 'Abbrechen' }).click();

  // An existing QCOW2 disk from a share is offered as boot source.
  await page.getByRole('button', { name: 'Neue VM' }).click();
  await expect(page.getByRole('dialog').getByRole('option', { name: /linux-cloud\.qcow2/ })).toBeAttached();
});

test('a graphics card can be passed through to a stopped virtual machine', async ({ page }) => {
  await page.goto('/#/vms');
  await page.getByRole('button', { name: 'Weitere Aktionen für E2E Gast' }).click();
  await page.getByRole('menuitem', { name: 'Grafikkarte und PCI-Geräte' }).click();
  const dialog = page.getByRole('dialog', { name: /Grafikkarte und PCI-Geräte/ });
  await expect(dialog.getByRole('checkbox', { name: /Demo-Beschleuniger/ })).toBeDisabled();
  await expect(dialog.getByText(/Teilt sich die IOMMU-Gruppe/)).toBeVisible();
  await dialog.getByRole('checkbox', { name: /Demo-Grafikkarte/ }).check();
  await dialog.getByRole('button', { name: 'Speichern' }).click();
  await expect(page.getByText('PCI-Geräte für „E2E Gast“ gespeichert.')).toBeVisible();
  // The card now belongs to that VM and is no longer free for another one.
  await page.getByRole('button', { name: 'Weitere Aktionen für linux-lab' }).click();
  await page.getByRole('menuitem', { name: 'Grafikkarte und PCI-Geräte' }).click();
  await expect(page.getByRole('dialog').getByText('Zugeordnet: andere VM')).toBeVisible();
});

test('share access can be changed per user', async ({ page }) => {
  await page.goto('/#/settings/shares');
  await page.getByRole('button', { name: 'Zugriff auf dokumente ändern' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Zugriff für patrick')).toHaveValue('write');
  await dialog.getByLabel('Zugriff für patrick').selectOption('read');
  await dialog.getByRole('button', { name: 'Speichern' }).click();
  await expect(page.getByText('Zugriff auf „dokumente“ geändert.')).toBeVisible();
  await page.getByRole('button', { name: 'Zugriff auf dokumente ändern' }).click();
  await expect(page.getByRole('dialog').getByLabel('Zugriff für patrick')).toHaveValue('read');
  await page.getByRole('dialog').getByLabel('Zugriff für patrick').selectOption('write');
  await page.getByRole('dialog').getByRole('button', { name: 'Speichern' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('a user can be created, locked and deleted', async ({ page }) => {
  await page.goto('/#/settings/users');
  await page.getByRole('button', { name: 'Benutzer anlegen' }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('Benutzername').fill('e2e-gast');
  await dialog.getByLabel('Passwort').fill('Sehr-Sicher-2026!x');
  await dialog.getByRole('button', { name: 'Anlegen' }).click();
  await expect(page.getByText('e2e-gast', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Benutzer e2e-gast bearbeiten' }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('Anmeldung').selectOption('off');
  await dialog.getByRole('button', { name: 'Speichern' }).click();
  await expect(page.getByText('Benutzer · gesperrt')).toBeVisible();

  await page.getByRole('button', { name: 'Benutzer e2e-gast bearbeiten' }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Löschen' }).click();
  await expect(dialog.getByRole('button', { name: 'Endgültig löschen' })).toBeDisabled();
  await dialog.getByRole('textbox').fill('e2e-gast');
  await dialog.getByRole('button', { name: 'Endgültig löschen' }).click();
  await expect(page.getByText('e2e-gast', { exact: true })).toHaveCount(0);
});

test('a storage quota can be set per user', async ({ page }) => {
  await page.goto('/#/settings/users');
  await page.getByRole('button', { name: 'Benutzer patrick bearbeiten' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Kontingent für dokumente in GB').fill('50');
  await dialog.getByRole('button', { name: 'Setzen' }).click();
  await expect(page.getByText('Kontingent für „dokumente“ auf 50 GB gesetzt.')).toBeVisible({ timeout: 20_000 });
  await expect(dialog.getByLabel('Kontingent für dokumente in GB')).toHaveValue('50');
});

test('own password, alerts and restart are available in settings', async ({ page }) => {
  await page.goto('/#/settings');
  await expect(page.getByText('Beispiel: Sicherungsziel fehlt')).toBeVisible();
  await page.getByRole('button', { name: 'Als gelesen markieren' }).click();
  await expect(page.getByText('Beispiel: Sicherungsziel fehlt')).toHaveCount(0);

  await page.getByRole('button', { name: 'Neu starten' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Neu starten' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('[aria-live=polite]')).toContainText(/Neustart|neu/i);

  await page.getByRole('button', { name: 'Mein Konto' }).click();
  await page.getByLabel('Aktuelles Passwort').fill('irgendein-altes');
  await page.getByLabel('Neues Passwort', { exact: true }).fill('Sehr-Sicher-2026!x');
  await page.getByLabel('Neues Passwort wiederholen').fill('Sehr-Sicher-2026!x');
  await page.getByRole('button', { name: 'Passwort ändern' }).click();
  await expect(page.getByText('Passwort geändert.')).toBeVisible({ timeout: 20_000 });
});

test('a backup to another drive can be configured, run and verified', async ({ page }) => {
  await page.goto('/#/settings/backups');
  await page.getByLabel('Sicherungsziel').selectOption('/var/media/demo-backup');
  await page.getByRole('button', { name: 'Speichern' }).click();
  await expect(page.getByText('Sicherungseinstellungen gespeichert.')).toBeVisible();
  test.skip(linuxOnly, 'the demo copies share files, which needs Linux');
  await page.getByRole('button', { name: 'Jetzt sichern' }).click();
  await expect(page.getByRole('button', { name: /Sicherung vom .* prüfen/ })).toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: /Sicherung vom .* prüfen/ }).click();
  await expect(page.locator('[aria-live=polite]')).toContainText(/geprüft|unverändert/);
});

test('a share can be mirrored continuously to another drive', async ({ page }) => {
  await page.goto('/#/settings/backups');
  await page.getByRole('button', { name: 'Einrichten' }).click();
  const dialog = page.getByRole('dialog', { name: 'Laufenden Abgleich einrichten' });
  await dialog.getByRole('combobox', { name: /^Ziel/ }).selectOption('/var/media/demo-backup');
  await dialog.getByLabel('Rhythmus').selectOption('1');
  await dialog.getByRole('button', { name: 'Einrichten' }).click();
  await expect(page.getByText('dokumente → /var/media/demo-backup/titan-sync/dokumente')).toBeVisible();
  await page.getByRole('button', { name: 'Abgleich für dokumente jetzt starten' }).click();
  await expect(page.getByText(/zuletzt .*Abgleich simuliert/)).toBeVisible();
  await page.getByRole('button', { name: 'Abgleich für dokumente entfernen' }).click();
  await expect(page.getByText('dokumente → /var/media/demo-backup/titan-sync/dokumente')).toHaveCount(0);
});

test('application rights and groups can be changed', async ({ page }) => {
  await page.goto('/#/settings/groups');
  await page.getByRole('group', { name: 'Apps und Docker für patrick' }).getByRole('button', { name: 'Erlaubt' }).click();
  await page.getByRole('button', { name: 'Neue Gruppe' }).click();
  const dialog = page.getByRole('dialog', { name: 'Neue Gruppe' });
  await dialog.getByLabel('Name').fill('familie-vm');
  await dialog.getByRole('checkbox', { name: 'familie' }).check();
  await dialog.getByRole('group', { name: 'Virtuelle Maschinen für die Gruppe' }).getByRole('button', { name: 'Erlaubt' }).click();
  await dialog.getByRole('button', { name: 'Übernehmen' }).click();
  await page.getByRole('button', { name: 'Änderungen speichern' }).click();
  await expect(page.getByText('Gruppen und Rechte gespeichert.')).toBeVisible({ timeout: 20_000 });
  await page.reload();
  await expect(page.getByRole('group', { name: 'Apps und Docker für patrick' }).getByRole('button', { name: 'Erlaubt' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('familie-vm')).toBeVisible();
  // The group grants VM access to its member without a personal override.
  await expect(page.getByRole('group', { name: 'Virtuelle Maschinen für familie' }).getByRole('button', { name: 'Wie Gruppe' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('derzeit erlaubt').first()).toBeVisible();
});

test('the system drive can be used fully and a new storage area created', async ({ page }) => {
  await page.goto('/#/settings/storage');
  await expect(page.getByText('Interner Speicher')).toBeVisible();
  await page.getByRole('button', { name: 'Ganze Platte nutzen' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Erweitern' }).click();
  await expect(page.getByRole('button', { name: 'Ganze Platte nutzen' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Neuer Speicherbereich' }).click();
  const dialog = page.getByRole('dialog', { name: 'Neuer Speicherbereich' });
  await dialog.getByLabel('Name').fill('medien');
  await dialog.getByLabel('Dateisystem').selectOption('btrfs');
  // Formatting stays locked until the exact drive path is typed.
  await expect(dialog.getByRole('button', { name: 'Formatieren und anlegen' })).toBeDisabled();
  await dialog.getByLabel('Bestätigung').fill('/dev/sdc');
  await dialog.getByRole('button', { name: 'Formatieren und anlegen' }).click();
  await expect(page.getByText('Speicherbereich „medien“ angelegt.')).toBeVisible();
  await expect(page.getByText('btrfs', { exact: true })).toBeVisible();
});

test('containers are listed with controls and logs', async ({ page }) => {
  await page.goto('/#/settings/docker');
  await expect(page.getByText('titan-jellyfin')).toBeVisible();
  await page.getByRole('button', { name: 'Protokoll von titan-jellyfin' }).click();
  await expect(page.getByRole('dialog')).toContainText('Demo');
  await page.keyboard.press('Escape');
  await page.getByRole('tab', { name: /Images/ }).click();
  await expect(page.getByText('nginx')).toBeVisible();
});

test('the web terminal opens a session without style violations', async ({ page }) => {
  const violations: string[] = [];
  page.on('console', entry => {
    if (/Content Security Policy/i.test(entry.text())) violations.push(entry.text());
  });
  await page.goto('/#/settings/terminal');
  await expect(page.locator('.xterm-screen')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.locator('.xterm-helper-textarea').focus();
  await page.keyboard.type('help');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(800);
  expect(violations).toEqual([]);
});

test('a plugged-in USB drive appears in the file manager and can be ejected', async ({ page }) => {
  await page.goto('/#/files');
  await page.getByRole('button', { name: 'USB-Stick', exact: true }).click();
  await expect(page.getByText('USB-Laufwerk „USB-Stick“')).toBeVisible();
  if (!linuxOnly) await expect(page.getByText('Urlaub.txt', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'USB-Stick auswerfen' }).click();
  await expect(page.getByText(/kann jetzt abgezogen werden/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'USB-Stick', exact: true })).toHaveCount(0);
});

test('apps and VM consoles open inside Titan and the system menu confirms before acting', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Syncthing öffnen' }).click();
  await expect(page).toHaveURL(/#\/open\/syncthing$/);
  await expect(page.locator('iframe[title="Syncthing"]')).toHaveAttribute('src', /:8384$/);
  await page.getByRole('button', { name: 'Zurück zur Startseite' }).click();

  await page.goto('/#/vms');
  const card = page.locator('div').filter({ hasText: /^linux-lab/ }).first();
  await expect(card).toBeVisible();
  const start = page.getByRole('button', { name: 'Starten' }).first();
  if (await start.isVisible()) await start.click();
  await page.getByRole('button', { name: 'Konsole' }).first().click();
  await expect(page).toHaveURL(/#\/vms\/[0-9a-f-]+$/);
  await expect(page.locator('iframe[title^="Konsole von"]')).toHaveAttribute('src', /console\.html\?vm=.*embedded=1/);

  await page.goto('/');
  await page.getByRole('button', { name: 'Systemmenü' }).click();
  await page.getByRole('menuitem', { name: 'Neu starten' }).click();
  await expect(page.getByRole('dialog', { name: 'NAS neu starten?' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Abbrechen' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
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
