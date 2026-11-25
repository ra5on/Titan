import type {ReadableStream} from 'node:stream/web'
import {createHash, randomUUID} from 'node:crypto'
import {createWriteStream} from 'node:fs'
import fs from 'node:fs/promises'
import net from 'node:net'
import path from 'node:path'
import {Readable, Transform} from 'node:stream'
import {pipeline} from 'node:stream/promises'
import {setTimeout as sleep} from 'node:timers/promises'
import {execa} from 'execa'
import {createWebSocketStream, type WebSocket} from 'ws'

import type Umbreld from '../../index.ts'
import type {AuthenticatedWebSocketRequest} from './index.ts'
import {OWNER_ACCOUNT_ID} from '../auth/auth.ts'

let loading: Promise<string> | undefined
async function viewerImage(umbreld: Umbreld) {
	const {image, sha256, size} = JSON.parse(
		await fs.readFile(new URL('../../../titan-viewer.json', import.meta.url), 'utf8'),
	)
	if (
		!/^sha256:[a-f0-9]{64}$/.test(image) ||
		!/^[a-f0-9]{64}$/.test(sha256) ||
		!Number.isSafeInteger(size) ||
		size <= 0
	)
		throw new Error('Invalid viewer image metadata')
	if ((await execa('docker', ['image', 'inspect', image], {reject: false})).exitCode === 0) return String(image)
	const folder = await fs.mkdtemp(path.join(umbreld.dataDirectory, '.titan-viewer-'))
	try {
		const url = `https://github.com/ra5on/Titan/releases/download/${umbreld.releaseVersion}/titan-viewer.tar.gz`
		const result = await fetch(url, {signal: AbortSignal.timeout(30 * 60_000)})
		if (!result.ok || !result.body) throw new Error('Viewer download unavailable')
		const hash = createHash('sha256')
		let bytes = 0
		const check = new Transform({
			transform(chunk: Buffer, _, cb) {
				bytes += chunk.length
				if (bytes > size) return cb(new Error('Unexpected viewer size'))
				hash.update(chunk)
				cb(null, chunk)
			},
		})
		const file = path.join(folder, 'image.tar.gz')
		await pipeline(
			Readable.fromWeb(result.body as ReadableStream),
			check,
			createWriteStream(file, {flags: 'wx', mode: 0o600}),
		)
		if (bytes !== size || hash.digest('hex') !== sha256) throw new Error('Invalid viewer archive checksum')
		await execa('docker', ['image', 'load', '-i', file])
		await execa('docker', ['image', 'inspect', image])
		return String(image)
	} finally {
		await fs.rm(folder, {recursive: true, force: true})
	}
}

export function createAppViewerHandler(umbreld: Umbreld) {
	const active = new Set<string>()
	return async (ws: WebSocket, req: AuthenticatedWebSocketRequest) => {
		if (req.authPrincipal?.accountId !== OWNER_ACCOUNT_ID) {
			ws.close(1008)
			return
		}
		const session = req.authPrincipal.sessionId
		if (active.has(session) || active.size >= 4) {
			ws.close(1013, 'Viewer already in use')
			return
		}
		active.add(session)
		const name = 'titan-viewer-' + randomUUID()
		const controller = new AbortController()
		ws.once('close', () => controller.abort())
		let dir: string | undefined
		let relay: net.Server | undefined
		let display: net.Socket | undefined
		const connections = new Set<net.Socket>()
		try {
			const params = new URL(req.url ?? '/', 'http://localhost').searchParams
			const appId = params.get('app') ?? ''
			const target = umbreld.lanIngress.viewerTarget(appId)
			const browserUrl = new URL(params.get('path') || '/', `${target.protocol}://127.0.0.1:8080`)
			if (browserUrl.origin !== `${target.protocol}://127.0.0.1:8080`) throw new Error('Invalid app path')
			const image = await (loading ??= viewerImage(umbreld).finally(() => {
				loading = undefined
			}))
			controller.signal.throwIfAborted()
			dir = await fs.mkdtemp('/run/titan-viewer-')
			await fs.chown(dir, 65534, 65534)
			const socketPath = path.join(dir, 'app.sock')
			relay = net.createServer((peer) => {
				const dest = net.connect(target.port, target.host)
				for (const socket of [peer, dest]) connections.add(socket)
				const close = () => {
					peer.destroy()
					dest.destroy()
					connections.delete(peer)
					connections.delete(dest)
				}
				peer.once('error', close)
				dest.once('error', close)
				peer.once('close', close)
				dest.once('close', close)
				peer.pipe(dest).pipe(peer)
			})
			await new Promise<void>((resolve, reject) => {
				relay!.once('error', reject)
				relay!.listen(socketPath, resolve)
			})
			await fs.chown(socketPath, 65534, 65534)
			await fs.chmod(socketPath, 0o600)
			await execa(
				'docker',
				[
					'run',
					'--detach',
					'--rm',
					'--pull=never',
					'--name',
					name,
					'--network',
					'none',
					'--read-only',
					'--user',
					'65534:65534',
					'--cap-drop',
					'ALL',
					'--security-opt',
					'no-new-privileges',
					'--pids-limit',
					'256',
					'--memory',
					'1g',
					'--cpus',
					'2',
					'--shm-size',
					'128m',
					'--tmpfs',
					'/tmp:rw,nosuid,nodev,size=384m',
					'--volume',
					dir + ':/session',
					image,
					browserUrl.href,
				],
				{timeout: 30000},
			)
			const sock = path.join(dir, 'display.sock')
			for (let i = 0; i < 150; i++) {
				controller.signal.throwIfAborted()
				if (
					await fs.stat(sock).then(
						(s) => s.isSocket(),
						() => false,
					)
				)
					break
				await sleep(100)
			}
			display = net.connect(sock)
			const stream = createWebSocketStream(ws)
			await Promise.all([
				pipeline(display, stream, {signal: controller.signal}),
				pipeline(stream, display, {signal: controller.signal}),
			])
		} catch (error) {
			if (!controller.signal.aborted) umbreld.logger.error('App viewer failed', error)
			ws.close(1011, 'App viewer unavailable')
		} finally {
			display?.destroy()
			relay?.close()
			for (const socket of connections) socket.destroy()
			if (dir) {
				await execa('docker', ['rm', '-f', name], {reject: false, timeout: 15000}).catch(() => {})
				await fs.rm(dir, {force: true, recursive: true}).catch(() => {})
			}
			active.delete(session)
		}
	}
}
