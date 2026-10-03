"""Bounded libvirt measurements; missing guest statistics remain unavailable."""
import math
import re
import threading
import time
from .core import Error


def parse_stats(output):
    records = {}; current = None
    for line in output.splitlines():
        match = re.fullmatch(r"Domain: '([^']+)'", line.strip())
        if match:
            current = {}; records[match[1]] = current
        elif current is not None:
            match = re.fullmatch(r'([a-zA-Z0-9_.]+)=([0-9]+)', line.strip())
            if match: current[match[1]] = int(match[2])
    return records


class VMMetricsMixin:
    def vm_measurements(self, records):
        if not records: return
        if not hasattr(self, '_vm_metric_lock'):
            self._vm_metric_lock = threading.Lock(); self._vm_metric_samples = {}
        ids = [record['id'] for record in records[:128]]
        try:
            stats = parse_stats(self.command(['virsh', 'domstats', '--raw', '--state', '--cpu-total', '--balloon', '--block', '--interface', *ids], timeout=15))
        except Error:
            stats = {}
        now = time.monotonic()
        with self._vm_metric_lock:
            previous = self._vm_metric_samples; fresh = {}
            for record in records:
                raw = stats.get('titan-' + record['name'], stats.get(record['id'], {}))
                sample = {'sampled_at': time.time(), 'cpu_percent': None, 'memory_resident_bytes': None,
                          'memory_guest_used_bytes': None, 'disk_allocated_bytes': record.get('disk_allocated_bytes'),
                          'disk_read_bps': None, 'disk_write_bps': None, 'network_rx_bps': None, 'network_tx_bps': None}
                def total(pattern):
                    found = [value for key,value in raw.items() if re.fullmatch(pattern,key)]
                    return sum(found) if found else None
                values = {'cpu': raw.get('cpu.time'), 'read': total(r'block.\d+.rd.bytes'), 'write': total(r'block.\d+.wr.bytes'),
                          'rx': total(r'net.\d+.rx.bytes'), 'tx': total(r'net.\d+.tx.bytes')}
                # Domain state and metrics come from the same libvirt sample.
                # A shutdown between the earlier domain listing and domstats must
                # never publish a stale balloon/RSS value.
                state = raw.get('state.state')
                if state in range(1,8): record['state'] = {1:'running',2:'blocked',3:'paused',4:'in shutdown',5:'shut off',6:'crashed',7:'pmsuspended'}[state]
                running = record['state'] == 'running'; active = record['state'] in ('running','paused','blocked','in shutdown','pmsuspended'); prior = previous.get(record['id'])
                if running and prior and .2 <= now-prior['time'] <= 120:
                    elapsed = now-prior['time']
                    for key,field in [('cpu','cpu_percent'),('read','disk_read_bps'),('write','disk_write_bps'),('rx','network_rx_bps'),('tx','network_tx_bps')]:
                        a,b = values[key],prior['values'][key]
                        if a is not None and b is not None and a >= b:
                            result=(a-b)/elapsed
                            if key=='cpu': result=min(100,max(0,result/1e9/max(1,record['cpus'])*100))
                            if math.isfinite(result): sample[field]=round(result,2)
                elif not running:
                    sample.update(cpu_percent=0,disk_read_bps=0,disk_write_bps=0,network_rx_bps=0,network_tx_bps=0)
                if not active:
                    sample.update(memory_resident_bytes=0, memory_guest_used_bytes=0)
                if active:
                    rss=raw.get('balloon.rss'); available=raw.get('balloon.available'); unused=raw.get('balloon.unused')
                    if rss is not None: sample['memory_resident_bytes']=rss*1024
                    if available is not None and unused is not None and 0<=unused<=available: sample['memory_guest_used_bytes']=(available-unused)*1024
                record['metrics']=sample
                fresh[record['id']]={'time':now,'values':values}
            self._vm_metric_samples=fresh
