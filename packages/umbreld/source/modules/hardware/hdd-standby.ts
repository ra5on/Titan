import {performance} from 'node:perf_hooks'

import {$} from 'execa'
import fse from 'fs-extra'
import PQueue from 'p-queue'

import type Umbreld from '../../index.ts'
import {getInternalStorageDevices} from './internal-storage.ts'

export const hddStandbyOptions = [0, 10, 20, 30, 60, 120] as const

type Activity = {signature: string; busy: boolean; idleSince: number; attempted: boolean; minutes: number}

export function nextHddActivity(previous: Activity | undefined, stat: string, now: number, minutes: number): Activity {
	const fields = stat.trim().split(/\s+/)
	if (fields.length < 11 || fields.some((field) => !/^\d+$/.test(field))) throw new Error('Invalid block statistics')
	// Completed read, write, discard and flush requests and the time spent processing I/O.
	const signature = [fields[0], fields[4], fields[9], fields[11], fields[15]].join(':')
	const busy = fields[8] !== '0'
	if (busy || !previous || previous.signature !== signature || previous.busy || previous.minutes !== minutes) {
		return {signature, busy, idleSince: now, attempted: false, minutes}
	}
	return previous
}

const diskPath = (id: string) => `/dev/disk/by-umbrel-id/${id}`

async function powerState(id: string) {
	const result = await $({reject: false, timeout: 3000})`hdparm -C ${diskPath(id)}`
	if (result.exitCode !== 0) return 'unsupported' as const
	if (result.stdout.includes('standby')) return 'standby' as const
	if (result.stdout.includes('active/idle')) return 'active' as const
	return 'unsupported' as const
}

export default class HddStandby {
	#umbreld: Umbreld
	#activities = new Map<string, Activity>()
	#queue = new PQueue({concurrency: 1})
	#timer?: NodeJS.Timeout
	#logger: Umbreld['logger']

	constructor(umbreld: Umbreld) {
		this.#umbreld = umbreld
		this.#logger = umbreld.logger.createChildLogger('hardware:hdd-standby')
	}

	start() {
		this.#timer = setInterval(() => {
			if (this.#queue.pending || this.#queue.size) return
			void this.#queue
				.add(() => this.#tick())
				.catch((error) => this.#logger.error('Could not manage HDD standby', error))
		}, 15_000).unref()
	}

	async stop() {
		clearInterval(this.#timer)
		await this.#queue.onIdle()
	}

	async #drives() {
		const drives = await getInternalStorageDevices({readSmart: false})
		return drives.filter((drive): drive is typeof drive & {id: string} => drive.type === 'hdd' && !!drive.id)
	}

	async list() {
		const preferences = (await this.#umbreld.store.get('hddStandbyMinutes')) ?? {}
		return Promise.all(
			(await this.#drives()).map(async ({id, name, serial, transport}) => ({
				id,
				name,
				serial,
				minutes: Object.hasOwn(preferences, id) ? preferences[id] : 0,
				state: transport === 'sata' ? await powerState(id) : ('unsupported' as const),
			})),
		)
	}

	async set(deviceIds: string[], minutes: number) {
		return this.#queue.add(async () => {
			if (!hddStandbyOptions.some((option) => option === minutes)) throw new Error('[hdd-standby-invalid-delay]')
			const drives = new Set((await this.#drives()).filter(({transport}) => transport === 'sata').map(({id}) => id))
			const supported = await Promise.all(
				deviceIds.map(async (id) => drives.has(id) && (await powerState(id)) !== 'unsupported'),
			)
			if (supported.includes(false)) throw new Error('[hdd-standby-unsupported]')
			const preferences = new Map(Object.entries((await this.#umbreld.store.get('hddStandbyMinutes')) ?? {}))
			for (const id of deviceIds) {
				this.#activities.delete(id)
				if (minutes === 0) preferences.delete(id)
				else preferences.set(id, minutes)
			}
			await this.#umbreld.store.set('hddStandbyMinutes', Object.fromEntries(preferences))
			return true
		})
	}

	async #tick() {
		const preferences = (await this.#umbreld.store.get('hddStandbyMinutes')) ?? {}
		if (Object.keys(preferences).length === 0) return
		if (this.#umbreld.backups.backupsInProgress.length > 0 || this.#umbreld.backups.restoreStatus.running) {
			this.#activities.clear()
			return
		}
		const status = await $({reject: false, timeout: 5000})`zpool status`
		if (status.exitCode !== 0 && !status.stderr.includes('no pools available')) return
		if (/^\s*(?:scan|expand|remove):.*in progress/im.test(status.stdout)) {
			this.#activities.clear()
			return
		}

		const activeIds = new Set<string>()
		for (const {id, device, transport} of await this.#drives()) {
			if (transport !== 'sata' || !Object.hasOwn(preferences, id) || !preferences[id]) continue
			activeIds.add(id)
			try {
				const path = `/sys/class/block/${device}`
				if ((await fse.readFile(`${path}/queue/rotational`, 'utf8')).trim() !== '1') continue
				const now = performance.now()
				const activity = nextHddActivity(
					this.#activities.get(id),
					await fse.readFile(`${path}/stat`, 'utf8'),
					now,
					preferences[id],
				)
				this.#activities.set(id, activity)
				if (activity.busy || activity.attempted || now - activity.idleSince < activity.minutes * 60_000) continue
				if ((await fse.realpath(diskPath(id))) !== `/dev/${device}` || (await powerState(id)) !== 'active') continue
				const check = nextHddActivity(
					activity,
					await fse.readFile(`${path}/stat`, 'utf8'),
					performance.now(),
					activity.minutes,
				)
				this.#activities.set(id, check)
				if (check !== activity) continue
				activity.attempted = true
				await $({timeout: 5000})`hdparm -y ${diskPath(id)}`
			} catch (error) {
				this.#logger.error(`Could not put ${id} into standby`, error)
			}
		}
		for (const id of this.#activities.keys()) {
			if (!activeIds.has(id)) this.#activities.delete(id)
		}
	}
}
