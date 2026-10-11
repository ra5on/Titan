import { expect, test } from '@playwright/test';

test('old bookmarks use one desktop and load no old shell', async ({ page }) => {
  const scripts: string[] = [];
  page.on('request', request => { if (request.resourceType() === 'script') scripts.push(new URL(request.url()).pathname); });
  await page.goto('/classic#security');
  await expect(page.getByRole('navigation', { name: 'Hauptnavigation' })).toHaveCount(1);
  await expect(page.locator('[data-security-center]')).toBeVisible();
  await expect(page.getByText('Klassische Oberfläche')).toHaveCount(0);
  expect(scripts).not.toContain('/app.js');
  expect(scripts).not.toContain('/workspace.js');
  await page.goto('/classic#settings?section=general');
  await expect(page.getByRole('heading', { name: 'Webzugriff', exact: true })).toBeVisible();
});

test('security settings preserve an edited form after a rejected save', async ({ page }) => {
  await page.goto('/#/settings/security');
  await page.locator('[data-security-tab="protection"]').click();
  const form = page.locator('[data-login-protection-form]');
  const attempts = form.locator('[name="ip_attempts"]');
  await attempts.fill('8');
  await page.route('**/api/security/login-protection', async route => {
    if (route.request().method() === 'POST') await route.fulfill({ status: 409, json: { error: 'Einstellungen wurden inzwischen geändert.' } });
    else await route.continue();
  });
  await form.getByRole('button', { name: 'Anmeldeschutz speichern' }).click();
  await expect(form.getByRole('alert')).toContainText('inzwischen geändert');
  await expect(attempts).toHaveValue('8');
});

test('Docker creation dialog and cancellation stay inside the desktop', async ({ page }) => {
  await page.goto('/#/settings/docker');
  await page.locator('[data-engine-action="create"]').click();
  const dialog = page.getByRole('dialog', { name: 'Container erstellen' });
  await expect(dialog.getByLabel('Docker-Image')).toBeVisible();
  await dialog.getByLabel('Name', { exact: true }).fill('unified-test');
  await dialog.getByRole('button', { name: 'Schließen', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.goto('/#/settings/services');
  await page.getByRole('button', { name: 'Neuer Dienst' }).click();
  await expect(page.getByRole('dialog', { name: 'Neuen Dienst anlegen' })).toBeVisible();
  await expect(page.locator('iframe')).toHaveCount(0);
});

test('VM snapshots can be created and restored as a new VM', async ({ page }) => {
  const list = await (await page.request.get('/api/vms')).json();
  const vm = list.vms.find((item: { state: string }) => item.state === 'shut off') || list.vms[0];
  await page.goto('/#/vms');
  const card = page.getByText(vm.display_name || vm.name, { exact: true }).locator('xpath=ancestor::div[contains(@class,"flex-col")][1]');
  await card.getByRole('button', { name: 'Bearbeiten', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: /Einstellungen ·/ });
  await dialog.getByRole('tab', { name: 'Sicherungen und Klone' }).click();
  await dialog.getByRole('button', { name: 'Snapshot erstellen', exact: true }).click();
  await dialog.getByLabel('Name', { exact: true }).fill('Vor Migration');
  if (vm.state !== 'shut off') await dialog.getByRole('checkbox', { name: /VM geordnet/ }).check();
  await dialog.getByRole('button', { name: 'Snapshot erstellen', exact: true }).click();
  await expect(dialog.getByText('Vor Migration', { exact: true })).toBeVisible({ timeout: 20_000 });
  await dialog.getByRole('button', { name: 'Als neue VM wiederherstellen' }).last().click();
  await dialog.getByLabel('Name', { exact: true }).fill('Wiederhergestellte Test-VM');
  await dialog.getByRole('button', { name: 'Als neue VM wiederherstellen' }).click();
  await expect(page.getByText('VM-Auftrag abgeschlossen.').last()).toBeVisible({ timeout: 20_000 });
  await expect.poll(async () => (await (await page.request.get('/api/vms')).json()).vms.some((item: { display_name: string }) => item.display_name === 'Wiederhergestellte Test-VM')).toBe(true);
});

test('maintenance and monitoring fit a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const section of ['storage', 'monitoring', 'security', 'docker', 'updates']) {
    await page.goto('/#/settings/' + section);
    if (section === 'storage') await page.getByText('Wartung, Wiederherstellungspunkte und Standardspeicher', { exact: true }).click();
    await expect(page.locator('div.management')).toBeVisible();
    await expect.poll(() => page.locator('div.management').evaluate(node => node.childElementCount)).toBeGreaterThan(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: `test-results/unified-${section}-mobile.png`, fullPage: true });
  }
});
