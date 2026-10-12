import { expect, test } from '@playwright/test';

test('Guacamole plugin installs without another account and opens apps inside Titan', async ({page}) => {
  await page.goto('/#/store/plugin-guacamole');
  await page.getByRole('button', {name:'Installieren', exact:true}).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Apache Guacamole');
  await expect(dialog.locator('input[type=password]')).toHaveCount(0);
  await dialog.getByRole('button', {name:'Installieren', exact:true}).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('button', {name:'Stoppen', exact:true})).toBeVisible();
  await page.route('**/api/apps', route => route.fulfill({json:{installed:[{id:'titan-tailscale', name:'Tailscale', port:0, scheme:'http', state:'running', status:'running'}]}}));
  await page.goto('/#/');
  await page.getByRole('button',{name:'Tailscale öffnen',exact:true}).click();
  await expect(page).toHaveURL(/#\/open\/titan-tailscale$/);
  await expect(page.getByText('Die Demo startet keine Fernsitzungen.')).toBeVisible();
  await expect(page.getByRole('button',{name:/neuem Tab|Neuer Tab/})).toHaveCount(0);
  expect(page.context().pages()).toHaveLength(1);
  await page.screenshot({path:'test-results/guacamole-app-window.png'});
  await page.goto('/#/store/plugin-guacamole');
  await page.getByRole('button',{name:'Deinstallieren',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('Browserdaten');
  await page.getByRole('dialog').getByRole('button',{name:'Deinstallieren',exact:true}).click();
  await expect(page.getByRole('button',{name:'Installieren',exact:true})).toBeVisible();
});

test('session window uses the same origin and fits above resized dock', async ({page}) => {
  await page.route('**/api/desktops/status', route => route.fulfill({json:{installed:true,running:true}}));
  await page.route('**/api/apps', route => route.fulfill({json:{installed:[{id:'titan-immich',name:'Immich',port:2283,state:'running'}]}}));
  await page.route('**/desktop.html?**', route => route.fulfill({contentType:'text/html',body:'<!doctype html><p>Private session fixture</p>'}));
  await page.goto('/#/open/titan-immich');
  const frame = page.getByTitle('Immich', {exact:true});
  await expect(frame).toHaveAttribute('src','/desktop.html?kind=app&target=titan-immich');
  const before = await frame.boundingBox();
  await page.evaluate(()=>document.documentElement.style.setProperty('--dock-clearance','200px'));
  const after = await frame.boundingBox();
  expect(after!.height).toBeLessThan(before!.height);
  expect(page.context().pages()).toHaveLength(1);
});
