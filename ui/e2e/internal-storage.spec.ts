import { expect, test } from '@playwright/test';

test('internal data stays usable when disk growth is unsupported', async ({ page }) => {
  await page.route('**/api/system-disk', route => route.fulfill({ json: {
    supported: false, available: false, reason: 'Das Partitionslayout kann nicht erweitert werden.',
  } }));
  await page.goto('/#/settings/storage');
  const internal = page.getByRole('region', { name: 'Interner Speicher', exact: true });
  await expect(internal).toContainText('bereits nutzbar');
  await expect(internal).toContainText('frei von');
  await expect(internal).toContainText('Erweiterung derzeit nicht verfügbar');
  await expect(internal.getByRole('button', { name: 'Ganze Platte nutzen' })).toHaveCount(0);
  await internal.getByRole('button', { name: 'Freigaben verwalten' }).click();
  await page.getByRole('button', { name: 'Neue Freigabe' }).click();
  await expect(page.getByRole('dialog').getByLabel('Speicherort')).toContainText('Interner Speicher');
});

test('internal storage can become the default without formatting a disk', async ({ page }) => {
  let selected = false;
  page.on('request', request => {
    if (request.url().endsWith('/api/actions') && request.method() === 'POST') {
      const body = request.postDataJSON();
      if (body.operation === 'storage_preferences_save' && body.arguments.default_storage === 'system') selected = true;
    }
  });
  await page.route('**/api/storage-locations', async route => {
    const response = await route.fetch();
    const data = await response.json();
    await route.fulfill({ json: { ...data, default_storage: selected ? 'system' : 'pool:tank' } });
  });
  await page.goto('/#/settings/storage');
  const internal = page.getByRole('region', { name: 'Interner Speicher', exact: true });
  await internal.getByRole('button', { name: 'Für neue Daten verwenden' }).click();
  await expect(internal.getByRole('button', { name: 'Standard für neue Daten' })).toBeDisabled();
  await expect(page.getByText('Vorhandene Daten bleiben an ihrem Speicherort.', { exact: false })).toBeVisible();
});

test('an offline internal mount remains visible with its error and no allocation button', async ({ page }) => {
  await page.route('**/api/storage-locations', route => route.fulfill({ json: {
    resources: [{ id: 'system', available: false, total_bytes: 0, free_bytes: 0, error: 'TITAN-DATA ist nicht eingehängt.' }],
    default_storage: 'system',
  } }));
  await page.route('**/api/system-disk', route => route.fulfill({ status: 503, json: { error: 'Prüfung fehlgeschlagen.' } }));
  await page.goto('/#/settings/storage');
  const internal = page.getByRole('region', { name: 'Interner Speicher', exact: true });
  await expect(internal).toContainText('TITAN-DATA ist nicht eingehängt.');
  await expect(internal).toContainText('Erweiterung derzeit nicht verfügbar');
  await expect(internal.getByRole('button')).toHaveCount(0);
});
