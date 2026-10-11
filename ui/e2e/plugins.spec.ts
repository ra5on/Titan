import { expect, test } from '@playwright/test';

test('Cloudflare plugin has a complete lifecycle and keeps token out of persisted browser state', async ({ page, request }) => {
  const token = Buffer.from(JSON.stringify({ a: 'a'.repeat(32), t: '2c9069cd-5cf1-470f-9ddd-df156d3f2c57', s: Buffer.from('only-a-disposable-test-secret-12345').toString('base64') })).toString('base64');
  await page.goto('/#/store');
  await page.getByRole('button', { name: /Cloudflare Tunnel Plugin/ }).click();
  await expect(page.getByText('Cloudflare-Ziel: Typ HTTP · URL 127.0.0.1:5102')).toBeVisible();
  await page.getByRole('button', { name: 'Installieren', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Plugin installieren' });
  await dialog.getByLabel('Tunnel-Token').fill(token);
  // Actual keystrokes catch focus-reset regressions caused by parent rerenders.
  await dialog.getByLabel('Öffentliche Titan-Adresse').pressSequentially('https://nas.example.org');
  await expect(dialog.getByLabel('Öffentliche Titan-Adresse')).toHaveValue('https://nas.example.org');
  await dialog.getByRole('button', { name: 'Installieren' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Stoppen', exact: true })).toBeVisible();
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain(token);
  expect(await (await request.get('/api/plugins')).text()).not.toContain(token);
  expect(await (await request.get('/api/jobs')).text()).not.toContain(token);
  await page.getByRole('button', { name: 'Nach Updates suchen' }).click();
  await expect(page.getByText('Letzte Prüfung')).toBeVisible();
  await page.getByRole('button', { name: 'Stoppen', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Stoppen' }).click();
  await expect(page.getByRole('button', { name: 'Starten', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Starten', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Stoppen', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Deinstallieren', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('lokale Adresse');
  await page.getByRole('dialog').getByRole('button', { name: 'Deinstallieren' }).click();
  await expect(page.getByRole('button', { name: 'Installieren', exact: true })).toBeVisible();
});

test('a rejected plugin installation retains the reviewed form', async ({ page }) => {
  await page.goto('/#/store/plugin-cloudflare');
  await page.getByRole('button', { name: 'Installieren', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Plugin installieren' });
  await dialog.getByLabel('Tunnel-Token').fill('invalid-token');
  await dialog.getByLabel('Öffentliche Titan-Adresse').fill('https://nas.example.org');
  await dialog.getByRole('button', { name: 'Installieren' }).click();
  await expect(dialog.getByRole('alert')).toBeVisible();
  await expect(dialog.getByLabel('Öffentliche Titan-Adresse')).toHaveValue('https://nas.example.org');
  await page.screenshot({ path: 'test-results/plugin-cloudflare-form.png', fullPage: true });
  await dialog.getByRole('button', { name: 'Abbrechen' }).click();
  await page.getByRole('button', { name: 'Installieren', exact: true }).click();
  await expect(dialog.getByLabel('Tunnel-Token')).toHaveValue('');
});
