import assert from 'node:assert/strict'
import {readFile, writeFile} from 'node:fs/promises'
import {setTimeout as sleep} from 'node:timers/promises'

import {createTRPCProxyClient, httpBatchLink} from '@trpc/client'

const [phase, passwordFile, poolsFile] = process.argv.slice(2)
const url = 'http://127.0.0.1:18080/trpc'
const unauthenticated = createTRPCProxyClient({links: [httpBatchLink({url})]})
const password = await readFile(passwordFile, 'utf8')

let token
for (let attempt = 0; !token && attempt < 120; attempt++) {
	try {
		token = await unauthenticated.user.login.mutate({password})
	} catch (error) {
		if (attempt === 119) throw error
		await sleep(5000)
	}
}
const client = createTRPCProxyClient({links: [httpBatchLink({url, headers: {authorization: `Bearer ${token}`}})]})
const paths = (listing) => listing.files.map(({path}) => path)

if (phase === 'shutdown') {
	await client.system.shutdown.mutate()
} else if (phase === 'create') {
	const devices = await client.hardware.dataPools.availableDevices.query()
	const disks = [1, 2, 3, 4].map((number) => {
		const disk = devices.find(({serial}) => serial === `TITANRAID${number}`)
		assert.ok(disk, `Test disk ${number} was not available for RAID`)
		return disk.id
	})
	const boot = (await client.hardware.internalStorage.getDevices.query()).find(({isSystemDrive}) => isSystemDrive)
	assert.ok(boot?.id)
	await assert.rejects(
		client.hardware.dataPools.create.mutate({name: 'Systemschutz', devices: [boot.id, disks[0]], confirmed: true}),
		/data-pool-disks-unavailable/,
	)
	await client.hardware.dataPools.create.mutate({name: 'VMs', devices: [disks[0], disks[1]], confirmed: true})
	await assert.rejects(
		client.hardware.dataPools.create.mutate({name: 'Doppelbelegung', devices: [disks[0], disks[2]], confirmed: true}),
		/data-pool-disks-unavailable/,
	)
	await client.hardware.dataPools.create.mutate({name: 'Dateien', devices: [disks[2], disks[3]], confirmed: true})
	const pools = await client.hardware.dataPools.list.query()
	assert.equal(pools.length, 2)
	assert.ok(pools.every(({mounted, health}) => mounted && health === 'ONLINE'))
	assert.deepEqual((await client.files.list.query({path: '/External'})).files.map(({name}) => name).sort(), [
		'Dateien',
		'VMs',
	])
	await client.files.createDirectory.mutate({path: '/Home/titan-main-storage-test'})
	for (const pool of pools) await client.files.createDirectory.mutate({path: `${pool.path}/titan-pool-test`})
	const rotating = await client.hardware.hddStandby.list.query()
	const drive = rotating.find(({id}) => id === disks[0])
	assert.ok(drive)
	if (drive.state !== 'unsupported') {
		await client.hardware.hddStandby.set.mutate({devices: [drive.id], minutes: 10})
		assert.equal((await client.hardware.hddStandby.list.query()).find(({id}) => id === drive.id)?.minutes, 10)
	} else {
		await assert.rejects(
			client.hardware.hddStandby.set.mutate({devices: [drive.id], minutes: 10}),
			/hdd-standby-unsupported/,
		)
	}
	await writeFile(poolsFile, JSON.stringify(pools), {mode: 0o600})
	console.log('Created two independent mirrors and verified disk reservation, Files and HDD settings')
	await client.system.shutdown.mutate()
} else if (phase === 'degraded') {
	const originals = JSON.parse(await readFile(poolsFile, 'utf8'))
	const degraded = originals.find(({name}) => name === 'VMs')
	const offline = originals.find(({name}) => name === 'Dateien')
	let pools
	for (let attempt = 0; attempt < 30; attempt++) {
		pools = await client.hardware.dataPools.list.query()
		if (pools.some(({id, mounted}) => id === degraded.id && mounted)) break
		await sleep(2000)
	}
	assert.equal(pools.length, 2)
	assert.deepEqual(
		pools.find(({id}) => id === degraded.id),
		{...degraded, health: 'DEGRADED', used: pools.find(({id}) => id === degraded.id).used},
	)
	assert.equal(pools.find(({id}) => id === offline.id)?.mounted, false)
	assert.ok(paths(await client.files.list.query({path: '/Home'})).includes('/Home/titan-main-storage-test'))
	assert.ok(paths(await client.files.list.query({path: degraded.path})).includes(`${degraded.path}/titan-pool-test`))
	await assert.rejects(
		client.files.createDirectory.mutate({path: `${offline.path}/must-not-fall-back`}),
		/data-pool-unavailable/,
	)
	console.log('Rebooted with a degraded mirror and an absent pool. Main storage and the remaining mirror worked.')
} else {
	throw new Error('Invalid storage test phase')
}
