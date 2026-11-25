import {constants} from 'node:fs'
import {copyFile, open} from 'node:fs/promises'

// Validate the same private copy qemu-img will convert. An upload can still be
// replaced or written to while the background install is running.
export async function snapshotQcow2(source: string, snapshot: string) {
	await copyFile(source, snapshot, constants.COPYFILE_EXCL | constants.COPYFILE_FICLONE)
	const file = await open(snapshot, 'r')
	try {
		const header = Buffer.alloc(104)
		const {bytesRead} = await file.read(header, 0, header.length, 0)
		const version = header.readUInt32BE(4)
		if (
			bytesRead < 72 ||
			header.readUInt32BE(0) !== 0x514649fb ||
			![2, 3].includes(version) ||
			header.readUInt32BE(32) !== 0
		)
			throw new Error('[machine-image-invalid]')
		if (header.readBigUInt64BE(8) !== 0n || header.readUInt32BE(16) !== 0) {
			throw new Error('[machine-image-backing-chain-not-supported]')
		}
		// v3 incompatible bits 3 and 4 describe compression and extended L2.
		// Refuse external data, corrupt/dirty disks and unknown required features.
		if (version === 3 && (bytesRead < 104 || (header.readBigUInt64BE(72) & ~0x18n) !== 0n)) {
			throw new Error('[machine-image-invalid]')
		}
	} finally {
		await file.close()
	}
}
