// Capture the README screenshots from a running demo server:
//   python3 -m titan.server --demo --port 5093 --data .demo/shots
//   node scripts/screenshots.mjs http://127.0.0.1:5093
import { chromium } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const base = process.argv[2] || 'http://127.0.0.1:5093';
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../docs/images');
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: 'de-DE' });
const page = await context.newPage();

const shot = async (name, route, prepare) => {
  await page.goto(base + '/#/' + route);
  await page.waitForLoadState('networkidle');
  if (prepare) await prepare();
  // Let entrance animations settle so no frame is captured half faded.
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(out, `titan-080-${name}.jpg`), type: 'jpeg', quality: 84 });
  console.log('saved', name);
};

// A start page that shows what it can hold: a pinned VM and an app in the dock.
await page.goto(base + '/');
const vms = await (await page.request.get(base + '/api/vms')).json();
await page.request.post(base + '/api/interface', {
  headers: { 'X-CSRF-Token': 'demo-only', 'Content-Type': 'application/json' },
  data: { pinned_vms: [vms.vms[0].id], dock: ['tool:home', 'tool:store', 'tool:files', 'tool:vms', 'app:jellyfin', 'tool:settings'] },
});

await shot('start', '');
await shot('store', 'store');
await shot('app-install', 'store/titan-immich');
await shot('app', 'apps/syncthing');
await shot('vms', 'vms');
await shot('storage', 'settings/storage');
await shot('backups', 'settings/backups');
await shot('rights', 'settings/groups');
await shot('docker', 'settings/docker');
await shot('appearance', '', async () => {
  await page.getByRole('button', { name: 'Systemmenü' }).click();
  await page.getByRole('menuitem', { name: 'Darstellung' }).click();
});

await browser.close();
