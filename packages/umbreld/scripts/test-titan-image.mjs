import {randomBytes} from 'node:crypto'
import path from 'node:path'
import {setTimeout as sleep} from 'node:timers/promises'
import {readFile} from 'node:fs/promises'
import {createTRPCProxyClient, httpBatchLink} from '@trpc/client'
import {chromium} from 'playwright'

const dir = process.argv[2]
const expected =
	process.env.TITAN_EXPECTED_VERSION ||
	JSON.parse(await readFile(new URL('../package.json', import.meta.url))).titanVersion
const base = 'http://127.0.0.1:18080'
const publicClient = createTRPCProxyClient({links: [httpBatchLink({url: base + '/trpc'})]})
let version
for (let attempt = 0; attempt < 180; attempt++) {
	try {
		version = await publicClient.system.version.query()
		break
	} catch {
		await sleep(5000)
	}
}
if (version?.releaseVersion !== expected)
	throw new Error(`Unexpected version from booted image: ${JSON.stringify(version)}`)
console.log(`Booted ${version.releaseName} from the NVMe image`)
const browser = await chromium.launch({
	headless: true,
	...(process.env.TITAN_TEST_BROWSER ? {executablePath: process.env.TITAN_TEST_BROWSER} : {channel: 'chrome'}),
})
try {
	const context = await browser.newContext({
		viewport: {width: 1440, height: 900},
		locale: 'de-DE',
		reducedMotion: 'reduce',
	})
	const page = await context.newPage()
	const upstream = new Set()
	page.on('request', (request) => {
		const url = new URL(request.url())
		if (
			/(^|\.)(umbrel\.com|umbrel\.dev|getumbrel\.github\.io)$/.test(url.hostname) ||
			(url.host === 'github.com' && url.pathname.startsWith('/getumbrel/'))
		)
			upstream.add(url.origin)
	})
	await page.goto(base)
	await page.locator('a[href^="/onboarding/create-account"]').waitFor()
	await page.evaluate(() => document.fonts.ready)
	await page.screenshot({path: path.join(dir, 'einrichtung.png')})
	const password = randomBytes(24).toString('hex')
	// Exercise the same account setup, login and cookies as a real browser.
	await page.locator('a[href^="/onboarding/create-account"]').click()
	await page.locator('form input:not([type="password"])').first().fill('Titan')
	const passwords = page.locator('form input[type="password"]')
	await passwords.nth(0).fill(password)
	await passwords.nth(1).fill(password)
	await page.locator('form button[type="submit"]').click()
	try {
		await page.getByTestId('to-desktop').click({timeout: 90000})
	} catch (error) {
		console.error(
			'Einrichtung abgebrochen auf',
			new URL(page.url()).pathname,
			(await page.locator('body').innerText()).slice(0, 1400),
		)
		throw error
	}
	await page.locator('[aria-label="Dateien"], [aria-label="Files"]').first().waitFor({timeout: 60000})
	await page.evaluate(() => document.fonts.ready)
	await page.screenshot({path: path.join(dir, 'desktop.png')})
	if (upstream.size) throw new Error('Browser contacted ' + [...upstream].join(', '))
} finally {
	await browser.close()
}
