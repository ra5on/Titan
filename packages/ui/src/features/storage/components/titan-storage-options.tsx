import {useId, useState} from 'react'
import {useTranslation} from 'react-i18next'
import {Link} from 'react-router-dom'

import {Button} from '@/components/ui/button'
import {Input} from '@/components/ui/input'
import {formatFilesystemSize} from '@/features/files/utils/format-filesystem-size'
import {trpcReact} from '@/trpc/trpc'

const selectClass = 'min-h-10 w-full rounded-xl border border-white/15 bg-neutral-900 px-3 text-sm text-white'

export function TitanStorageOptions() {
	return (
		<div className='mt-6 grid gap-4 lg:grid-cols-2'>
			<DataPools />
			<HddStandby />
		</div>
	)
}

function DataPools() {
	const {t} = useTranslation()
	const utils = trpcReact.useUtils()
	const pools = trpcReact.hardware.dataPools.list.useQuery(undefined, {refetchInterval: 15_000})
	const [adding, setAdding] = useState(false)
	const [name, setName] = useState('')
	const [first, setFirst] = useState('')
	const [second, setSecond] = useState('')
	const [confirmed, setConfirmed] = useState(false)
	const nameId = useId()
	const drives = trpcReact.hardware.dataPools.availableDevices.useQuery(undefined, {enabled: adding})
	const create = trpcReact.hardware.dataPools.create.useMutation({
		onSuccess: async () => {
			setAdding(false)
			setName('')
			setFirst('')
			setSecond('')
			setConfirmed(false)
			await Promise.all([
				utils.hardware.dataPools.invalidate(),
				utils.hardware.internalStorage.getDevices.invalidate(),
				utils.files.invalidate(),
			])
		},
	})
	const selected = (drives.data ?? []).filter(({id}) => id === first || id === second)
	const canCreate = name.trim().length > 0 && selected.length === 2 && confirmed && !create.isPending

	return (
		<section className='flex min-w-0 flex-col gap-3 rounded-24 border border-white/10 bg-white/5 p-5'>
			<div className='flex flex-wrap items-center justify-between gap-3'>
				<h2 className='text-17 font-semibold'>{t('titan-storage.pools')}</h2>
				<Button
					type='button'
					variant='default'
					size='sm'
					onClick={() => {
						setAdding(!adding)
						setConfirmed(false)
						create.reset()
					}}
					disabled={create.isPending}
				>
					{adding ? t('cancel') : t('titan-storage.add-pool')}
				</Button>
			</div>
			{pools.isError && (
				<p role='alert' className='text-sm text-red-300'>
					{t('titan-storage.read-error')}
				</p>
			)}
			{pools.data?.length === 0 && <p className='text-sm text-white/60'>{t('titan-storage.no-pools')}</p>}
			{pools.data?.map((pool) => (
				<div key={pool.id} className='flex flex-col gap-2 rounded-xl border border-white/10 px-3 py-3 text-sm'>
					<div className='flex flex-wrap items-center justify-between gap-2'>
						<span className='min-w-0 font-medium break-words'>{pool.name}</span>
						<span className={pool.mounted && pool.health === 'ONLINE' ? 'text-green-300' : 'text-amber-200'}>
							{!pool.mounted
								? t('titan-storage.pool-unavailable')
								: pool.health === 'ONLINE'
									? t('titan-storage.pool-online')
									: pool.health === 'DEGRADED'
										? t('titan-storage.pool-degraded')
										: pool.health}
						</span>
					</div>
					<span className='text-xs text-white/55'>
						RAID 1{pool.size > 0 ? ` · ${formatFilesystemSize(pool.used)} / ${formatFilesystemSize(pool.size)}` : ''}
					</span>
					{pool.devices.map((id) => (
						<span key={id} className='text-xs break-all text-white/55'>
							{id}
						</span>
					))}
					{pool.mounted && (
						<Link className='self-start text-sm underline underline-offset-4' to={`/files${pool.path}`}>
							{t('titan-storage.open-pool')}
						</Link>
					)}
				</div>
			))}
			{adding && (
				<form
					className='flex flex-col gap-3 border-t border-white/10 pt-3'
					onSubmit={(event) => {
						event.preventDefault()
						if (canCreate) create.mutate({name, devices: [first, second], confirmed: true})
					}}
				>
					<label className='text-sm' htmlFor={nameId}>
						{t('titan-storage.pool-name')}
					</label>
					<Input
						id={nameId}
						maxLength={48}
						value={name}
						onChange={(event) => setName(event.target.value)}
						disabled={create.isPending}
						required
					/>
					{drives.isPending && <p className='text-sm text-white/60'>{t('titan-storage.checking-drives')}</p>}
					{drives.isError && (
						<p role='alert' className='text-sm text-red-300'>
							{t('titan-storage.read-error')}
						</p>
					)}
					{drives.data && drives.data.length < 2 && (
						<p className='text-sm text-white/60'>{t('titan-storage.requires-two-drives')}</p>
					)}
					{(drives.data?.length ?? 0) >= 2 && (
						<>
							{[
								{label: t('titan-storage.drive-one'), value: first, other: second, set: setFirst},
								{label: t('titan-storage.drive-two'), value: second, other: first, set: setSecond},
							].map(({label, value, other, set}) => (
								<label key={label} className='flex flex-col gap-1 text-sm'>
									{label}
									<select
										className={selectClass}
										value={value}
										onChange={(event) => {
											set(event.target.value)
											setConfirmed(false)
										}}
										disabled={create.isPending}
										required
									>
										<option value=''>{t('titan-storage.choose-drive')}</option>
										{drives.data?.map((drive) => (
											<option key={drive.id} value={drive.id} disabled={drive.id === other}>
												{drive.name} · {drive.serial} · {formatFilesystemSize(drive.size)}
											</option>
										))}
									</select>
								</label>
							))}
							<label className='flex items-start gap-2 rounded-xl border border-amber-200/20 bg-amber-200/5 p-3 text-sm text-amber-100'>
								<input
									className='mt-0.5 size-4 shrink-0'
									type='checkbox'
									checked={confirmed}
									onChange={(event) => setConfirmed(event.target.checked)}
									disabled={create.isPending}
								/>
								{t('titan-storage.confirm-create')}
							</label>
							<Button type='submit' className='self-start' disabled={!canCreate}>
								{create.isPending ? t('titan-storage.creating-pool') : t('titan-storage.create-pool')}
							</Button>
						</>
					)}
					{create.isError && (
						<p role='alert' className='text-sm text-red-300'>
							{t('titan-storage.create-error')} {create.error.message}
						</p>
					)}
				</form>
			)}
		</section>
	)
}

function HddStandby() {
	const {t} = useTranslation()
	const utils = trpcReact.useUtils()
	const drives = trpcReact.hardware.hddStandby.list.useQuery(undefined, {refetchInterval: 15_000})
	const save = trpcReact.hardware.hddStandby.set.useMutation({
		onSuccess: () => utils.hardware.hddStandby.list.invalidate(),
	})

	return (
		<section className='flex min-w-0 flex-col gap-3 rounded-24 border border-white/10 bg-white/5 p-5'>
			<h2 className='text-17 font-semibold'>{t('titan-storage.standby')}</h2>
			<p className='text-sm text-white/60'>{t('titan-storage.standby-description')}</p>
			{drives.isError && (
				<p role='alert' className='text-sm text-red-300'>
					{t('titan-storage.read-error')}
				</p>
			)}
			{drives.data?.length === 0 && <p className='text-sm text-white/55'>{t('titan-storage.no-hdds')}</p>}
			{drives.data?.map((drive) => (
				<label
					className='flex flex-col gap-2 rounded-xl border border-white/10 p-3 text-sm sm:flex-row sm:items-center'
					key={drive.id}
				>
					<div className='min-w-0 flex-1'>
						<p className='break-words'>
							{drive.name} <span className='text-xs text-white/55'>{drive.serial}</span>
						</p>
						<p className='text-xs text-white/60' aria-live='polite'>
							{drive.state === 'active'
								? t('titan-storage.hdd-active')
								: drive.state === 'standby'
									? t('titan-storage.hdd-sleeping')
									: t('titan-storage.hdd-unsupported')}
						</p>
					</div>
					<select
						className={`${selectClass} sm:w-36`}
						aria-label={t('titan-storage.hdd-delay', {drive: drive.name})}
						value={drive.minutes}
						disabled={drive.state === 'unsupported' || save.isPending}
						onChange={(event) => save.mutate({devices: [drive.id], minutes: Number(event.target.value)})}
					>
						<option value={0}>{t('titan-storage.standby-off')}</option>
						{[10, 20, 30, 60, 120].map((minutes) => (
							<option key={minutes} value={minutes}>
								{t('titan-storage.standby-minutes', {minutes})}
							</option>
						))}
					</select>
				</label>
			))}
			{save.isError && (
				<p role='alert' className='text-sm text-red-300'>
					{t('titan-storage.standby-error')}
				</p>
			)}
		</section>
	)
}
