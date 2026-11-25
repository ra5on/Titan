import {trpcReact} from '@/trpc/trpc'

type Share = {path: string; tag: string; readOnly: boolean}

export function HostDevices({
	groups,
	shares,
	disabled,
	onGroups,
	onShares,
}: {
	groups: string[]
	shares: Share[]
	disabled: boolean
	onGroups: (groups: string[]) => void
	onShares: (shares: Share[]) => void
}) {
	const query = trpcReact.machines.pciGroups.useQuery()
	const devices = query.data ?? []
	return (
		<fieldset disabled={disabled} className='space-y-3 disabled:opacity-60'>
			<legend className='text-15 font-medium'>GPU / NPU · PCI</legend>
			{!devices.length && (
				<p className='text-13 text-white/60'>
					Für die Zuweisung muss die IOMMU-Gruppe auf dem Host an vfio-pci gebunden sein.
				</p>
			)}
			{[...new Set([...groups, ...devices.map((d) => d.key)])].map((key) => (
				<label key={key} className='flex items-center gap-2 text-13'>
					<input
						type='checkbox'
						checked={groups.includes(key)}
						onChange={(e) => onGroups(e.target.checked ? [...groups, key] : groups.filter((k) => k !== key))}
					/>
					{devices.find((d) => d.key === key)?.label ?? key}
				</label>
			))}
			<h3 className='pt-2 text-15 font-medium'>Ordner über virtiofs freigeben</h3>
			{shares.map((share, index) => {
				const edit = (patch: Partial<Share>) => onShares(shares.map((s, i) => (i === index ? {...s, ...patch} : s)))
				return (
					<div key={index} className='grid gap-2 rounded-lg bg-white/5 p-3 text-13'>
						<label>
							Ordner{' '}
							<input
								className='w-full rounded bg-black/30 p-2'
								value={share.path}
								placeholder='/Home/Medien'
								onChange={(e) => edit({path: e.target.value})}
							/>
						</label>
						<label>
							Mount-Tag im Gast{' '}
							<input
								className='w-full rounded bg-black/30 p-2'
								value={share.tag}
								onChange={(e) => edit({tag: e.target.value})}
							/>
						</label>
						<label>
							<input type='checkbox' checked={share.readOnly} onChange={(e) => edit({readOnly: e.target.checked})} />{' '}
							Nur lesen
						</label>
						<button
							type='button'
							className='justify-self-start text-white/70'
							onClick={() => onShares(shares.filter((_, i) => i !== index))}
						>
							Freigabe entfernen
						</button>
					</div>
				)
			})}
			<button
				type='button'
				disabled={shares.length >= 8}
				className='rounded-lg bg-white/10 px-3 py-2 text-13'
				onClick={() =>
					onShares([
						...shares,
						{
							path: '',
							tag: `share${Array.from({length: 9}, (_, i) => i + 1).find((i) => !shares.some((s) => s.tag === `share${i}`))}`,
							readOnly: true,
						},
					])
				}
			>
				Ordner hinzufügen
			</button>
		</fieldset>
	)
}
