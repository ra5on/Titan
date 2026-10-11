import { expect, test } from '@playwright/test';

test('files can be created, edited with conflict protection, copied and restored from trash', async ({ page, request }) => {
  const name = `workspace-${Date.now()}.txt`;
  const destination = name + '-copies';
  expect((await request.post('/api/files', { headers: { 'X-CSRF-Token': 'demo-only' }, data: { share: 'dokumente', action: 'mkdir', path: destination } })).ok()).toBe(true);
  await page.goto('/#/files');
  await page.getByRole('button', { name: 'dokumente', exact: true }).first().click();
  await page.getByRole('button', { name: 'Neue Datei', exact: true }).click();
  let dialog = page.getByRole('dialog', { name: 'Neue Datei' });
  await dialog.getByLabel('Dateiname', { exact: true }).fill(name);
  await dialog.getByLabel('Dateiinhalt').fill('Erste Version ✓');
  await dialog.getByRole('button', { name: 'Speichern' }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole('button', { name: `Weitere Aktionen für ${name}`, exact: true }).click();
  await page.getByRole('menuitem', { name: 'Text bearbeiten' }).click();
  dialog = page.getByRole('dialog', { name: 'Text bearbeiten' });
  await expect(dialog.getByLabel('Dateiinhalt')).toHaveValue('Erste Version ✓');
  await dialog.getByLabel('Dateiinhalt').fill('Zweite Version ✓');
  await page.route('**/api/files', async route => {
    if (route.request().postDataJSON()?.action === 'write') await route.fulfill({ status: 409, json: { error: 'Datei wurde inzwischen verändert.' } });
    else await route.continue();
  });
  await dialog.getByRole('button', { name: 'Speichern' }).click();
  await expect(dialog.getByRole('alert')).toContainText('inzwischen verändert');
  await expect(dialog.getByLabel('Dateiinhalt')).toHaveValue('Zweite Version ✓');
  await page.unroute('**/api/files');
  await dialog.getByRole('button', { name: 'Speichern' }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole('button', { name: `Weitere Aktionen für ${name}`, exact: true }).click();
  await page.getByRole('menuitem', { name: 'Kopieren', exact: true }).click();
  dialog = page.getByRole('dialog', { name: 'Kopieren' });
  await dialog.getByLabel('Zielordner').fill(destination);
  await dialog.getByRole('button', { name: 'Kopieren', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole('button', { name: `${name} in den Papierkorb` }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Verschieben' }).click();
  await expect(page.getByRole('link', { name: `${name} herunterladen` })).toHaveCount(0);
  await page.getByRole('button', { name: 'Papierkorb', exact: true }).click();
  dialog = page.getByRole('dialog', { name: 'Papierkorb' });
  const option = dialog.getByRole('option').filter({ hasText: name });
  await dialog.getByRole('combobox').selectOption(await option.getAttribute('value') || '');
  await dialog.getByRole('button', { name: 'Wiederherstellen' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('link', { name: `${name} herunterladen` })).toBeVisible();
});

test('root access creates a root terminal only after authentication and can be revoked', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/api/root-terminal')) requests.push(request.postData() || '');
  });
  await page.goto('/#/settings/terminal');
  await page.getByRole('button', { name: 'Root-Modus aktivieren' }).click();
  const dialog = page.getByRole('dialog', { name: 'Root-Modus aktivieren' });
  expect(requests).toHaveLength(0);
  await dialog.getByLabel('Aktuelles Passwort').fill('demo-password');
  await dialog.getByRole('button', { name: 'Root-Modus aktivieren' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('Root-Terminal · endet mit dem Root-Modus.')).toBeVisible();
  await expect.poll(() => requests.some(value => JSON.parse(value).action === 'create')).toBe(true);
  await page.getByRole('button', { name: 'Root-Modus beenden' }).click();
  await expect(page.getByText('Das Terminal läuft ohne Root-Rechte im Datenbereich des NAS.')).toBeVisible();
});
