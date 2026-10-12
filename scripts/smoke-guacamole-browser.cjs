const { chromium } = require('../ui/node_modules/playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1200,height:850}});
    const base = process.env.TITAN_GUAC_URL;
    const login = await page.request.post(base + '/api/login', {data:{name:'tester',password:'Disposable-Guac-proof-123!'},headers:{Origin:base}});
    assert.equal(login.status(),200,await login.text());
    const errors=[]; page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/desktop.html?kind=app&target=fixture');
    await page.getByRole('status').filter({hasText:'Verbunden'}).waitFor({timeout:60000});
    await page.locator('#screen canvas').first().waitFor();
    await page.locator('#screen').focus();
    await page.keyboard.type('TitanGuacamole');
    await page.keyboard.press('Enter');
    await page.screenshot({path:'artifacts/guacamole-runtime.png'});
    await page.getByRole('button',{name:'Neu verbinden',exact:true}).click();
    await page.getByRole('status').filter({hasText:'Verbunden'}).waitFor({timeout:15000});
    const session = await page.request.get(base + '/api/session').then(r=>r.json());
    const logout = await page.request.post(base + '/api/logout',{data:{},headers:{Origin:base,'X-CSRF-Token':session.user.csrf}});
    assert.equal(logout.status(),200,await logout.text());
    await page.getByRole('status').filter({hasText:/Verbindung getrennt|Sitzung nicht bereit/}).waitFor({timeout:10000});
    assert.deepEqual(errors,[]);
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
