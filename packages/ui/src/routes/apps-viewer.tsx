import RFB from '@novnc/novnc'
import {useEffect, useRef, useState} from 'react'
import {useNavigate, useParams, useSearchParams} from 'react-router-dom'
import {trpcClient} from '@/trpc/trpc'

export default function AppViewer() {
	const {appId} = useParams()
	const [params] = useSearchParams()
	const appPath = params.get('path') ?? '/'
	const screen = useRef<HTMLDivElement>(null)
	const navigate = useNavigate()
	const [status, setStatus] = useState('Die App-Ansicht startet. Beim ersten Öffnen lädt Titan den Browser herunter.')
	useEffect(() => {
		if (!appId) return
		let disposed = false
		let rfb: RFB | undefined
		let socket: WebSocket | undefined
		async function connect() {
			const ticket = await trpcClient.user.createWebSocketTicket.mutate({target: 'viewer'})
			if (disposed || !screen.current) return
			const url = new URL('/apps/viewer', location.href)
			url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
			url.searchParams.set('app', appId!)
			url.searchParams.set('path', appPath)
			url.searchParams.set('ticket', ticket)
			socket = new WebSocket(url, ['binary'])
			socket.binaryType = 'arraybuffer'
			rfb = new RFB(screen.current, socket, {shared: true})
			rfb.scaleViewport = true
			rfb.addEventListener('connect', () => setStatus(''))
			rfb.addEventListener('disconnect', () => {
				if (!disposed) setStatus('Die Verbindung zur App wurde beendet.')
			})
		}
		void connect().catch(() => {
			if (!disposed) setStatus('Die App-Ansicht konnte nicht gestartet werden.')
		})
		return () => {
			disposed = true
			rfb?.disconnect()
			socket?.close()
		}
	}, [appId, appPath])
	return (
		<section
			aria-label={appId}
			className='fixed inset-3 z-50 flex flex-col overflow-hidden rounded-2xl border border-white/15 bg-neutral-950 text-white shadow-2xl'
		>
			<header className='flex items-center justify-between border-b border-white/10 px-5 py-3'>
				<h1 className='text-16 font-semibold'>{appId}</h1>
				<button type='button' onClick={() => navigate('/')} className='rounded-md bg-white/10 px-3 py-1.5 text-13'>
					Schließen
				</button>
			</header>
			{status && (
				<p role='status' className='px-5 py-3 text-14'>
					{status}
				</p>
			)}
			<div ref={screen} className='min-h-0 flex-1' />
		</section>
	)
}
