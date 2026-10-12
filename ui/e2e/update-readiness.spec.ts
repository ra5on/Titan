import { expect, test } from '@playwright/test';

for (const [scenario, version, digest] of [
  ['normal reboot', '0.8.1', 'a'], ['prepared update', '0.8.4', 'b'], ['prepared rollback', '0.8.0', 'c'],
]) {
 for (const entry of ['settings', 'menu']) {
  test(`${entry} reboot confirms the displayed next boot: ${scenario}`, async ({ page }) => {
    const selected = { version, digest: 'sha256:' + digest.repeat(64) };
    let next = selected;
    let statusReads = 0;
    const actions: unknown[] = [];
    await page.route('**/api/updates/system', route => {
      statusReads++;
      return route.fulfill({ json: { booted: { version: '0.8.1', digest: 'sha256:' + 'a'.repeat(64) },
        next_boot: next, reboot_scheduled: false } });
    });
    await page.route('**/api/actions', async route => {
      actions.push(route.request().postDataJSON());
      // Intercept every mutation; this test never schedules even a demo reboot.
      await route.fulfill({ status: 409, json: { error: 'Geplanter Systemstand hat sich geändert.' } });
    });
    await page.goto(entry === 'settings' ? '/#/settings/system' : '/');
    if (entry === 'menu') await page.getByRole('button', { name: 'Systemmenü' }).click();
    await page.getByRole('button', { name: 'Neu starten', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'NAS neu starten?' });
    await expect(dialog).toContainText(`Titan startet mit Version ${version}`);
    expect(actions).toHaveLength(0);
    expect(statusReads).toBe(1);
    // A second administrator changes the selection after the dialog opens.
    next = { version: '0.8.5', digest: 'sha256:' + 'd'.repeat(64) };
    await dialog.getByRole('button', { name: 'Neu starten', exact: true }).click();
    await expect.poll(() => actions.length).toBe(1);
    expect(actions[0]).toEqual({ operation: 'system_reboot', arguments: {
      expected_digest: selected.digest, confirmation: 'NEUSTART',
    } });
    expect(statusReads).toBe(1);
    await expect(page.getByText('Geplanter Systemstand hat sich geändert.', { exact: true })).toBeVisible();
  });
 }
}

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
