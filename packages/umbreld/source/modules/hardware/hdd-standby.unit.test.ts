import {expect, test} from 'vitest'

import {nextHddActivity} from './hdd-standby.ts'

test('an I/O completion, in-flight I/O or a policy change restarts idle timing', () => {
	const stat = (read: number, inFlight: number, flush: number) =>
		[read, 0, 0, 0, 0, 0, 0, 0, inFlight, 0, 0, 0, 0, 0, 0, flush, 0].join(' ')
	const idle = nextHddActivity(undefined, stat(1, 0, 0), 0, 10)
	idle.attempted = true
	expect(nextHddActivity(idle, stat(1, 0, 0), 60, 10)).toBe(idle)
	const busy = nextHddActivity(idle, stat(1, 1, 0), 61, 10)
	expect(busy).toMatchObject({busy: true, idleSince: 61, attempted: false})
	const completed = nextHddActivity(busy, stat(2, 0, 0), 70, 10)
	expect(completed).toMatchObject({busy: false, idleSince: 70, attempted: false})
	const flushed = nextHddActivity(completed, stat(2, 0, 1), 80, 10)
	expect(flushed.idleSince).toBe(80)
	expect(nextHddActivity(flushed, stat(2, 0, 1), 90, 30).idleSince).toBe(90)
})
