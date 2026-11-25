import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import {afterEach, beforeEach, expect, test} from 'vitest'

import {folderShareSchema, listPciGroups, pciHostdevXml} from './host-devices.ts'

let root: string
beforeEach(async () => {
	root = await fs.mkdtemp(path.join(os.tmpdir(), 'titan-iommu-'))
})
afterEach(async () => {
	await fs.rm(root, {recursive: true, force: true})
})

async function addFunction(group: string, address: string, cls: string, driver: string) {
	const dir = path.join(root, group, 'devices', address)
	await fs.mkdir(dir, {recursive: true})
	await fs.writeFile(path.join(dir, 'class'), cls)
	await fs.writeFile(path.join(dir, 'vendor'), '0x8086')
	await fs.writeFile(path.join(dir, 'device'), '0x1234')
	await fs.symlink('/sys/bus/pci/drivers/' + driver, path.join(dir, 'driver'))
}
test('offers complete reserved GPU/audio and NPU groups, excluding host-owned and mixed groups', async () => {
	await addFunction('21', '0000:01:00.0', '0x030000', 'vfio-pci')
	await addFunction('21', '0000:01:00.1', '0x040300', 'vfio-pci')
	await addFunction('32', '0000:02:00.0', '0x120000', 'vfio-pci')
	await addFunction('40', '0000:03:00.0', '0x030000', 'i915')
	await addFunction('50', '0000:04:00.0', '0x030000', 'vfio-pci')
	await addFunction('50', '0000:04:00.1', '0x010800', 'vfio-pci')
	const devices = await listPciGroups(root)
	expect(devices.map((g) => g.addresses)).toEqual([['0000:01:00.0', '0000:01:00.1'], ['0000:02:00.0']])
	expect(devices[1].label).toContain('NPU')
	expect(pciHostdevXml(devices[0].addresses[1])).toContain("domain='0x0000' bus='0x01' slot='0x00' function='0x1'")
})
test('shares require a named directory below Home and an explicit guest mount tag', () => {
	for (const virtualPath of ['/Home', '/Home/', '/Home/../System', '/External/one', '/Home/./a']) {
		expect(folderShareSchema.safeParse({path: virtualPath, tag: 'data', readOnly: true}).success).toBe(false)
	}
	expect(folderShareSchema.safeParse({path: '/Home/Media', tag: 'media', readOnly: true}).success).toBe(true)
})
