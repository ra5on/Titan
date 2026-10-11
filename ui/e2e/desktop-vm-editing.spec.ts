import { expect, test } from '@playwright/test';

for (const size of ['small', 'medium', 'large']) {
  test(`console clears the ${size} dock on desktop and phone`, async ({ page }) => {
    await page.route('**/api/interface', async route => {
      const response = await route.fetch();
      await route.fulfill({ json: { ...await response.json(), dock_size: size } });
    });
    await page.goto('/#/vms');
    const machines = await (await page.request.get('/api/vms')).json();
    await page.goto(`/#/vms/${machines.vms[0].id}`);
    const dock = page.getByRole('navigation', { name: 'Hauptnavigation' });
    const window = page.getByRole('region', { name: 'VM-Konsole' }).locator(':scope > div');
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await expect.poll(async () => {
        const a = await window.boundingBox(), b = await dock.boundingBox();
        return a && b ? b.y - (a.y + a.height) : -1;
      }).toBeGreaterThanOrEqual(11);
      await expect(dock.locator('ul')).toHaveCSS('overflow-x', 'visible');
      // Tooltips deliberately extend beyond the dock's glass surface. Check
      // the controls themselves: every icon must remain inside the viewport.
      for (const button of await dock.getByRole('button').all()) {
        const box = await button.boundingBox();
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width).toBeLessThanOrEqual(width);
      }
    }
  });
}

test('VM hardware can be edited and survives reopening', async ({ page }) => {
  await page.goto('/#/vms');
  await page.getByRole('button', { name: 'Neue VM' }).click();
  const create = page.getByRole('dialog', { name: 'Neue virtuelle Maschine' });
  await create.getByLabel('Name', { exact: true }).fill('Hardware Test');
  await create.getByRole('button', { name: 'Anlegen' }).click();
  await expect(create).toHaveCount(0);
  // Find the card by its displayed name, independent of its grid position.
  const edit = page.getByText('Hardware Test', { exact: true }).locator('xpath=ancestor::div[contains(@class,"flex-col")][1]').getByRole('button', { name: 'Bearbeiten', exact: true });
  await edit.click();
  const dialog = page.getByRole('dialog', { name: 'Einstellungen · Hardware Test' });
  await dialog.getByLabel('CPU-Kerne', { exact: true }).fill('3');
  await dialog.getByLabel('RAM (MiB)', { exact: true }).fill('6144');
  await dialog.getByRole('button', { name: 'Einstellungen speichern' }).click();
  await expect(page.getByText('VM-Einstellungen gespeichert.', { exact: true })).toBeVisible();
  await dialog.getByRole('tab', { name: 'Laufwerke und ISO' }).click();
  await dialog.getByLabel('CD/DVD-Medium').selectOption('');
  await dialog.getByRole('button', { name: 'Medium speichern' }).click();
  await expect(page.getByText('Installationsmedium gespeichert.', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: 'Laufwerk hinzufügen' }).click();
  await expect(dialog.getByText(/vdb · Zusätzliches Laufwerk/)).toBeVisible();
  await dialog.getByRole('tab', { name: 'Netzwerk', exact: true }).click();
  await dialog.getByRole('button', { name: 'Bearbeiten', exact: true }).click();
  await dialog.getByLabel('Netzwerkkartenmodell').selectOption('e1000');
  await dialog.getByRole('button', { name: 'Netzwerkkarte speichern' }).click();
  await expect(dialog.getByText(/Netzwerkkarte 1.*e1000/)).toBeVisible();
  await dialog.getByRole('button', { name: 'Schließen', exact: true }).last().click();
  await edit.click();
  await expect(dialog.getByLabel('CPU-Kerne', { exact: true })).toHaveValue('3');
  await expect(dialog.getByLabel('RAM (MiB)', { exact: true })).toHaveValue('6144');
});
