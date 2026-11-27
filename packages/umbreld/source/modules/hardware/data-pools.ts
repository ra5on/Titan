import {randomUUID} from 'node:crypto'
import {join} from 'node:path'

import {$} from 'execa'
import fse from 'fs-extra'
import PQueue from 'p-queue'

import type Umbreld from '../../index.ts'
import type {StorageDevice} from './internal-storage.ts'

export type DataPool = {id: string; name: string; devices: [string, string]}

export const dataPoolMountPrefix = 'titan-raid-'
export const dataPoolPathPattern = /^\/External\/(titan-raid-([a-f0-9-]{36}))(?:\/|$)/
const diskDirectory = '/dev/disk/by-umbrel-id'

function poolName({id}: DataPool) {
	return `titan-data-${id}`
}

function virtualPath({id}: DataPool) {
	return `/External/${dataPoolMountPrefix}${id}`
}

// Mount-table fields octal-escape whitespace and backslashes, even within a filename.
function unescapeMountInfo(value: string) {
	return value.replace(/\\([0-7]{3})/g, (_, octal: string) => String.fromCharCode(Number.parseInt(octal, 8)))
}

async function readZfsMounts() {
	const mounts = new Map<string, string>()
	for (const line of (await fse.readFile('/proc/self/mountinfo', 'utf8')).split('\n')) {
		const [mount, filesystem] = line.split(' - ')
		const target = mount?.split(' ')[4]
		const [type, source] = filesystem?.split(' ') ?? []
		if (type === 'zfs' && source && target) mounts.set(unescapeMountInfo(target), unescapeMountInfo(source))
	}
	return mounts
}

async function isUnusedDisk(device: StorageDevice) {
	const expectedPath = `/dev/${device.device}`
	const diskPath = join(diskDirectory, device.id!)
	if ((await fse.realpath(diskPath)) !== expectedPath) return false
	const {stdout} = await $`lsblk --json --output KNAME,TYPE,RO,MOUNTPOINTS --tree ${diskPath}`
	const {blockdevices} = JSON.parse(stdout) as {
		blockdevices: Array<{
			kname: string
			type: string
			ro: boolean
			mountpoints: Array<string | null>
			children?: object[]
		}>
	}
	const [disk] = blockdevices
	if (blockdevices.length !== 1 || !disk || disk.kname !== device.device || disk.type !== 'disk' || disk.ro)
		return false
	if (disk.children?.length || disk.mountpoints.some(Boolean)) return false
	if ((await fse.readdir(`/sys/class/block/${device.device}/holders`)).length) return false
	const {stdout: signatures} = await $`wipefs --no-act --noheadings --output TYPE ${diskPath}`
	return signatures.trim() === ''
}

export default class DataPools {
	#queue = new PQueue({concurrency: 1})
	#stopListening?: () => void
	#logger: Umbreld['logger']
	#umbreld: Umbreld

	constructor(umbreld: Umbreld) {
		this.#umbreld = umbreld
		this.#logger = umbreld.logger.createChildLogger('hardware:data-pools')
	}

	async #pools() {
		return (await this.#umbreld.store.get('dataPools')) ?? []
	}

	async memberIds() {
		return new Set((await this.#pools()).flatMap(({devices}) => devices))
	}

	async availableDevices() {
		const reserved = await this.memberIds()
		const devices = await this.#umbreld.hardware.internalStorage.getDevices({readSmart: false})
		const candidates = devices.filter(
			(device): device is StorageDevice & {id: string} =>
				!!device.id && device.isSystemDrive === false && !reserved.has(device.id) && device.size >= 1024 ** 3,
		)
		const checked = await Promise.all(
			candidates.map(async (device) => ((await isUnusedDisk(device).catch(() => false)) ? device : undefined)),
		)
		return checked.filter((device) => device !== undefined)
	}

	#mountPath(pool: DataPool) {
		return this.#umbreld.files.virtualToSystemPathUnsafe(virtualPath(pool))
	}

	async assertMounted(path: string) {
		const match = path.match(dataPoolPathPattern)
		if (!match) return
		const pool = (await this.#pools()).find(({id}) => id === match[2])
		if (!pool || (await readZfsMounts()).get(this.#mountPath(pool)) !== poolName(pool)) {
			throw new Error('[data-pool-unavailable]')
		}
	}

	async #importAndMount(pool: DataPool) {
		const name = poolName(pool)
		const mountPath = this.#mountPath(pool)
		if ((await readZfsMounts()).get(mountPath) === name) return false

		const imported = await $({reject: false, timeout: 15_000})`zpool list -H -o name ${name}`
		if (imported.exitCode !== 0) {
			const devices = pool.devices.flatMap((id) => [join(diskDirectory, id), join(diskDirectory, `${id}-part1`)])
			// Import only the recorded pool, searching only its own disks. A mirror may come up degraded.
			const present = await Promise.all(devices.map(async (device) => ((await fse.pathExists(device)) ? device : null)))
			const search = present.flatMap((device) => (device ? ['-d', device] : []))
			if (search.length === 0) return false
			const result = await $({reject: false, timeout: 15_000})`zpool import -N -o cachefile=none ${search} ${name}`
			if (result.exitCode !== 0) {
				this.#logger.log(`Could not import ${name}: ${result.stderr}`)
				return false
			}
		}

		await fse.ensureDir(mountPath, {mode: 0o500})
		const stats = await fse.lstat(mountPath)
		if (
			!stats.isDirectory() ||
			(await fse.realpath(mountPath)) !== mountPath ||
			(await fse.readdir(mountPath)).length
		) {
			throw new Error('[data-pool-mountpoint-in-use]')
		}
		await $({timeout: 15_000})`mount -t zfs -o nodev,nosuid ${name} ${mountPath}`
		await this.#umbreld.files.chownSystemPath(mountPath)
		return true
	}

	async start() {
		const mountPools = () =>
			this.#queue.add(async () => {
				const results = await Promise.all(
					(await this.#pools()).map((pool) =>
						this.#importAndMount(pool).catch((error) => {
							this.#logger.error(`Could not mount ${poolName(pool)}`, error)
							return false
						}),
					),
				)
				return results.some(Boolean)
			})
		await mountPools()
		this.#stopListening = this.#umbreld.eventBus.on('system:disk:change', async () => {
			if (await mountPools()) await this.#umbreld.files.samba.applyShares()
		})
	}

	async stop() {
		this.#stopListening?.()
		await this.#queue.add(async () => {
			const mounts = await readZfsMounts()
			await Promise.all(
				(await this.#pools()).map(async (pool) => {
					const path = this.#mountPath(pool)
					try {
						if (mounts.get(path) === poolName(pool)) await $({timeout: 10_000})`umount ${path}`
						await $({reject: false, timeout: 10_000})`zpool export ${poolName(pool)}`
					} catch (error) {
						this.#logger.error(`Could not export ${poolName(pool)}`, error)
					}
				}),
			)
		})
	}

	async create(name: string, devices: [string, string]) {
		return this.#umbreld.hardware.raid.withAdditionalPoolCreation(() =>
			this.#queue.add(async () => {
				const pools = await this.#pools()
				if (pools.some((pool) => pool.name.toLowerCase() === name.toLowerCase()))
					throw new Error('[data-pool-name-in-use]')
				const eligible = new Map((await this.availableDevices()).map((device) => [device.id, device]))
				const first = eligible.get(devices[0])
				const second = eligible.get(devices[1])
				if (!first || !second || first.device === second.device) throw new Error('[data-pool-disks-unavailable]')

				const pool = {id: randomUUID(), name, devices}
				await this.#umbreld.store.set('dataPools', [...pools, pool])
				try {
					if (!(await isUnusedDisk(first)) || !(await isUnusedDisk(second)))
						throw new Error('[data-pool-disks-unavailable]')
					const paths = devices.map((device) => join(diskDirectory, device))
					await $`zpool create -o cachefile=none -o failmode=continue -o ashift=12 -O compression=lz4 -m legacy ${poolName(pool)} mirror ${paths}`
				} catch (error) {
					const result = await $({reject: false})`zpool list -H -o name ${poolName(pool)}`
					if (result.exitCode !== 0) await this.#umbreld.store.set('dataPools', pools)
					throw error
				}
				try {
					await this.#importAndMount(pool)
				} catch (error) {
					this.#logger.error(`Created ${poolName(pool)} but it could not be mounted`, error)
				}
				return true
			}),
		)
	}

	async list() {
		const pools = await this.#pools()
		if (pools.length === 0) return []
		const mounts = await readZfsMounts()
		const result = await $({reject: false, timeout: 5_000})`zpool list -Hp -o name,health,size,alloc`
		const status = new Map(result.stdout.split('\n').map((row) => [row.split('\t')[0], row.split('\t').slice(1)]))
		return pools.map((pool) => {
			const [health, size, used] = status.get(poolName(pool)) ?? []
			return {
				...pool,
				path: virtualPath(pool),
				mounted: mounts.get(this.#mountPath(pool)) === poolName(pool),
				health: health ?? 'UNAVAILABLE',
				size: Number(size) || 0,
				used: Number(used) || 0,
			}
		})
	}

	async mountedLocations() {
		const pools = await this.#pools()
		if (pools.length === 0) return []
		const mounts = await readZfsMounts()
		return pools
			.filter((pool) => mounts.get(this.#mountPath(pool)) === poolName(pool))
			.map((pool) => ({name: pool.name, path: virtualPath(pool)}))
	}
}
