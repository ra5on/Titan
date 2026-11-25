import {randomBytes} from 'node:crypto'
import path from 'node:path'
import {setTimeout as sleep} from 'node:timers/promises'
import {readFile} from 'node:fs/promises'
import {createTRPCProxyClient, httpBatchLink} from '@trpc/client'
import {chromium} from 'playwright'

const dir = process.argv[2]
const expected = JSON.parse(await readFile(new URL('../package.json', import.meta.url))).titanVersion
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
const browser = await chromium.launch({channel: 'chrome', headless: true})
try {
	const context = await browser.newContext({viewport: {width: 1440, height: 900}, locale: 'de-DE'})
	const page = await context.newPage()
	const client = createTRPCProxyClient({
		links: [
			httpBatchLink({
				url: base + '/trpc',
				fetch: async (url, init) => {
					const response = await context.request.fetch(String(url), {
						method: init?.method,
						headers: Object.fromEntries(new Headers(init?.headers)),
						data: init?.body,
					})
					return new Response(await response.body(), {status: response.status(), headers: response.headers()})
				},
			}),
		],
	})
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
	await page.locator('body').filter({hasText: /\S/}).waitFor()
	await page.screenshot({path: path.join(dir, 'einrichtung.png')})
	const name = 'Titan'
	const password = randomBytes(24).toString('hex')
	await client.user.register.mutate({name, password})
	let token
	for (let attempt = 0; attempt < 120; attempt++) {
		try {
			token = await client.user.login.mutate({name, password})
			if (token) break
		} catch {}
		await sleep(2000)
	}
	if (typeof token !== 'string') throw new Error('Could not sign in to the booted image')
	await context.addInitScript((value) => localStorage.setItem('umbrel-auth-token', value), token)
	await page.goto(base)
	await page.waitForURL((url) => !/(onboarding|login)/.test(url.pathname))
	await page.locator('body').filter({hasText: /\S/}).waitFor()
	await page.screenshot({path: path.join(dir, 'desktop.png')})
	if (upstream.size) throw new Error('Browser contacted ' + [...upstream].join(', '))
} finally {
	await browser.close()
}
