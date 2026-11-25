import {readdir, readFile, readlink} from 'node:fs/promises'
import path from 'node:path'

import {z} from 'zod'

const pciAddress = /^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$/
export const pciAssignmentSchema = z
	.string()
	.max(640)
	.regex(/^[0-9a-f:.@,-]+$/)
export const folderShareSchema = z.object({
	path: z
		.string()
		.max(1024)
		.startsWith('/Home/')
		.refine((value) =>
			value
				.slice(6)
				.split('/')
				.every((part) => part.length > 0 && !['.', '..'].includes(part) && !part.includes('\0')),
		),
	tag: z.string().regex(/^[a-zA-Z0-9_-]{1,32}$/),
	readOnly: z.boolean(),
})

export type FolderShare = z.infer<typeof folderShareSchema>

// Select whole IOMMU groups. A group is eligible only if every function is
// already reserved for VFIO, including a graphics card's HDMI audio function.
export async function listPciGroups(root = '/sys/kernel/iommu_groups') {
	const groups = await readdir(root).catch(() => [])
	const devices = await Promise.all(
		groups
			.map(async (group) => {
				const dir = path.join(root, group, 'devices')
				const addresses = (await readdir(dir)).sort()
				if (!addresses.length || !addresses.every((address) => pciAddress.test(address))) return
				const functions = await Promise.all(
					addresses.map(async (address) => {
						const sys = path.join(dir, address)
						const [vendor, device, classId, driver] = await Promise.all([
							readFile(path.join(sys, 'vendor'), 'utf8'),
							readFile(path.join(sys, 'device'), 'utf8'),
							readFile(path.join(sys, 'class'), 'utf8'),
							readlink(path.join(sys, 'driver')).catch(() => ''),
						])
						return {
							address,
							vendor: vendor.trim().slice(2),
							device: device.trim().slice(2),
							classId: classId.trim().slice(2),
							driver: path.basename(driver),
						}
					}),
				)
				const supported = functions.filter(({classId}) => /^(03|12)/.test(classId))
				if (
					!supported.length ||
					functions.some(({classId, driver}) => driver !== 'vfio-pci' || !/^(03|12|0403)/.test(classId))
				)
					return
				const key = functions.map((f) => `${f.address}@${f.vendor}:${f.device}`).join(',')
				return {
					key,
					group,
					addresses,
					label: supported
						.map((f) => `${f.classId.startsWith('03') ? 'GPU' : 'NPU'} ${f.vendor}:${f.device} (${f.address})`)
						.join(', '),
				}
			})
			.map((promise) => promise.catch(() => undefined)),
	)
	return devices.filter((group) => group !== undefined).sort((a, b) => a.key.localeCompare(b.key))
}

export async function resolvePciAssignments(keys: string[]) {
	if (!keys.length) return []
	const groups = await listPciGroups()
	return keys.flatMap((key) => {
		const group = groups.find((candidate) => candidate.key === key)
		if (!group) throw new Error('The assigned PCI device is missing or its IOMMU group is not reserved for VFIO.')
		return group.addresses
	})
}

export function pciHostdevXml(address: string) {
	if (!pciAddress.test(address)) throw new Error('Invalid PCI address')
	const [domain, bus, slot, fn] = address.split(/[:.]/)
	return `<hostdev mode='subsystem' type='pci' managed='no'><source><address domain='0x${domain}' bus='0x${bus}' slot='0x${slot}' function='0x${fn}'/></source></hostdev>`
}
