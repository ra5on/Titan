import { expect, test } from '@playwright/test';

test('live boot health overrides a cached installable offer and stays visible during polling', async ({ page }) => {
  let healthy = false;
  await page.route('**/api/session', async route => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), demo: false } });
  });
  await page.route('**/api/updates', route => route.fulfill({ json: {
    current: '0.8.1', latest: 'v0.8.4', channel: 'stable', selection_kind: 'all',
    available: true, signed: true, checked: Date.now() / 1000,
  } }));
  await page.route('**/api/updates/system', async route => {
    const response = await route.fetch();
    // No new reason field: also cover the status exposed by a 0.8.1 agent.
    await route.fulfill({ json: { ...await response.json(), health_confirmed: healthy,
      update_blocked_reason: null, reboot_required: false, reboot_scheduled: false } });
  });
  await page.goto('/#/settings/updates');
  const install = page.getByRole('button', { name: 'Update vorbereiten', exact: true });
  await expect(install).toBeDisabled();
  await expect(page.getByText('Installation gesperrt', { exact: true })).toBeVisible();
  await expect(page.locator('[data-update-blocked-reason]')).toContainText('Startprüfung');
  healthy = true;
  // Re-render the offer using fresh status, then exercise the live polling gate.
  await page.reload();
  await expect(install).toBeEnabled();
  await expect(page.locator('[data-update-blocked-reason]')).toHaveCount(0);
  healthy = false;
  await expect(install).toBeDisabled({ timeout: 10_000 });
  await expect(page.locator('[data-update-blocked-reason]')).toContainText('Startprüfung');
});
