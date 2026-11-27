import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'

import {expect, test, vi} from 'vitest'

import {OFFICIAL_APP_STORE_REPO, UMBREL_APP_STORE_REPO} from '../../constants.ts'
import type Umbreld from '../../index.ts'
import type {Context} from '../server/trpc/context.ts'
import {readManifestInDirectory} from './app.ts'
import AppStore, {sanitizeRegistry} from './app-store.ts'
import {apps as appsRouter} from './routes.ts'

test('public registry excludes repository locations and undeclared manifest fields', () => {
	const registry = [
		{
			url: 'https://user:secret@example.internal/private-store.git?token=secret',
			meta: {id: 'community', name: 'Community', internal: 'not public'},
			apps: [
				{
					appStoreId: 'community',
					manifestVersion: '2.0.0',
					id: 'community-example',
					name: 'Example',
					tagline: 'An example app',
					icon: 'https://example.com/icon.svg',
					category: 'Utilities',
					version: '1.2.3',
					port: 3000,
					description: 'Description',
					website: 'https://example.com',
					repo: 'https://example.com/source',
					support: 'https://example.com/support',
					gallery: ['https://example.com/screenshot.png'],
					defaultPassword: 'manifest-password',
					path: '/admin',
					privateExtension: {token: 'manifest-secret'},
				},
			],
		},
	] as unknown as Parameters<typeof sanitizeRegistry>[0]

	const sanitized = sanitizeRegistry(registry, '2.0.0-beta.1')

	expect(sanitized).toHaveLength(1)
	expect(sanitized[0].meta).toStrictEqual({id: 'community', name: 'Community'})
	expect(sanitized[0]).not.toHaveProperty('url')
	expect(sanitized[0].apps[0]).toMatchObject({
		appStoreId: 'community',
		id: 'community-example',
		name: 'Example',
		repo: 'https://example.com/source',
		compatible: true,
	})
	expect(sanitized[0].apps[0]).not.toHaveProperty('port')
	expect(sanitized[0].apps[0]).not.toHaveProperty('path')
	expect(sanitized[0].apps[0]).not.toHaveProperty('defaultPassword')
	expect(sanitized[0].apps[0]).not.toHaveProperty('privateExtension')
})

test('apps.list returns catalog icons for existing official, bundled and community installs', async () => {
	const dataDirectory = await mkdtemp(join(tmpdir(), 'titan-installed-icons-'))
	try {
		const communityUrl = 'https://github.com/example/community-apps'
		const logger = {log: vi.fn(), error: vi.fn(), verbose: vi.fn()}
		const server = {
			dataDirectory,
			version: '2.1.0-beta.2',
			store: {get: async (key: string) => key === 'appRepositories' ? [communityUrl] : undefined},
			logger: {...logger, createChildLogger: () => logger},
		} as unknown as Umbreld
		const store = new AppStore(server, {defaultAppStoreRepo: UMBREL_APP_STORE_REPO})
		const [bundled, official, community] = await store.getRepositories()
		await mkdir(community.path, {recursive: true})
		await writeFile(join(community.path, 'umbrel-app-store.yml'), 'id: community\nname: Community\n')
		const template = (await readFile(join(bundled.path, 'freshrss/umbrel-app.yml'), 'utf8')).replace(/^icon: .*\n/m, '')
		const instances = await Promise.all(['freshrss', 'tailscale', 'murmur', 'community-example'].map(async (id) => {
			const manifest = template.replace(/^id: freshrss$/m, `id: ${id}`)
			if (id !== 'freshrss') {
				const repository = id === 'community-example' ? community : official
				const directory = join(repository.path, id)
				await mkdir(directory, {recursive: true})
				const icon = id === 'community-example' ? 'https://example.com/community.svg' : ''
				await writeFile(join(directory, 'umbrel-app.yml'), icon ? `${manifest}\nicon: ${icon}\n` : manifest)
			}
			const directory = join(dataDirectory, 'app-data', id)
			await mkdir(directory, {recursive: true})
			await writeFile(join(directory, 'umbrel-app.yml'), id === 'murmur' ? `${manifest}\nicon: https://example.com/murmur.svg\n` : manifest)
			return {
				id,
				readManifest: () => readManifestInDirectory(directory),
				getSelectedDependencies: async () => [],
				shouldAutoStart: async () => true,
				getAppProxyAuth: async () => true,
				getStorageSettings: async () => [],
				getEnvironmentSettings: async () => [],
				store: {get: async () => undefined},
			}
		}))
		const caller = appsRouter.createCaller({
			umbreld: server,
			appStore: store,
			apps: {logger, instances},
			logger,
			transport: 'express',
			dangerouslyBypassAuthentication: true,
		} as unknown as Context)
		const icons = Object.fromEntries((await caller.list()).map(({id, icon}) => [id, icon]))
		expect(icons).toEqual({
			freshrss: 'https://freshrss.org/images/icon.svg',
			tailscale: 'https://getumbrel.github.io/umbrel-apps-gallery/tailscale/icon.svg',
			murmur: 'https://example.com/murmur.svg',
			'community-example': 'https://example.com/community.svg',
		})
	} finally {
		await rm(dataDirectory, {force: true, recursive: true})
	}
})

test('includes official apps once in the Titan storefront and resolves their installation templates', async () => {
	const dataDirectory = await mkdtemp(join(tmpdir(), 'titan-app-store-'))
	try {
		const server = {
			dataDirectory,
			version: '2.1.0-beta.2',
			store: {get: async () => [UMBREL_APP_STORE_REPO, 'https://github.com/getumbrel/umbrel-apps/']},
			logger: {createChildLogger: () => ({log: vi.fn(), error: vi.fn()})},
		} as unknown as Umbreld
		const store = new AppStore(server, {defaultAppStoreRepo: UMBREL_APP_STORE_REPO})
		const repositories = await store.getRepositories()
		expect(repositories.map(({url}) => url)).toEqual([UMBREL_APP_STORE_REPO, OFFICIAL_APP_STORE_REPO])
		const [bundled, official] = repositories

		expect((await store.publicRegistry())[0].apps.map(({id}) => id)).toEqual(['freshrss'])

		const manifest = await readFile(join(bundled.path, 'freshrss/umbrel-app.yml'), 'utf8')
		for (const id of ['freshrss', 'official-example']) {
			const directory = join(official.path, id)
			await mkdir(directory, {recursive: true})
			await writeFile(
				join(directory, 'umbrel-app.yml'),
				manifest
					.replace(/^id: freshrss$/m, `id: ${id}`)
					.replace(/^icon: .*\n/m, '')
					.replace('gallery: []', 'gallery: [1.webp]'),
			)
		}

		const [catalog, ...remaining] = await store.publicRegistry()
		expect(remaining).toEqual([])
		expect(catalog.apps.map(({id}) => id)).toEqual(['freshrss', 'official-example'])
		expect(catalog.apps[1]).toMatchObject({
			compatible: true,
			icon: 'https://getumbrel.github.io/umbrel-apps-gallery/official-example/icon.svg',
			gallery: ['https://getumbrel.github.io/umbrel-apps-gallery/official-example/1.webp'],
		})
		await expect(store.getAppTemplateFilePath('official-example')).resolves.toBe(
			join(official.path, 'official-example'),
		)
		await expect(store.getAppTemplateFilePath('freshrss')).resolves.toBe(join(bundled.path, 'freshrss'))
	} finally {
		await rm(dataDirectory, {force: true, recursive: true})
	}
})
