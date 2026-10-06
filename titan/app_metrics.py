"""Observed Docker resource statistics, queried only for verified managed containers."""
import json
import math
import re
from .core import Error


def amount(value):
    match=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*(B|kB|MB|GB|TB|KiB|MiB|GiB|TiB)',str(value))
    if not match:return None
    units={'B':1,'kB':1000,'MB':1000**2,'GB':1000**3,'TB':1000**4,'KiB':1024,'MiB':1024**2,'GiB':1024**3,'TiB':1024**4}
    return int(float(match[1])*units[match[2]])


def parse_stats(output):
    result={}
    for line in output.splitlines()[:256]:
        try:
            row=json.loads(line);name=row['Name'];cpu=float(row['CPUPerc'].rstrip('%'))
            if not isinstance(name,str) or not math.isfinite(cpu) or cpu<0:continue
            memory=amount(row.get('MemUsage','').split('/')[0].strip())
            disk=[amount(part.strip()) for part in row.get('BlockIO','').split('/')]
            result[name]={'cpu_percent':round(cpu,1),'memory_bytes':memory,'disk_read_bytes':disk[0] if len(disk)==2 else None,'disk_write_bytes':disk[1] if len(disk)==2 else None}
        except (ValueError,KeyError,TypeError,AttributeError):continue
    return result


class AppMetricsMixin:
    def op_app_metrics(self):
        from .app_management import _run
        targets={};memory_totals={};records=self.load('apps',[])
        for record in records[:128]:
            try:
                checked=self.managed_app(record['id'])
                from .catalog import APPS
                recipe=APPS[record['id']];stack=recipe.get('stack')
                # The installed definition may intentionally omit Office. Do
                # not inspect six recipe members for a valid four-service app.
                if stack:
                    from pathlib import Path
                    definition=json.loads((Path(self.directory)/'apps'/record['id']/'compose.json').read_text())
                    names=list(definition['services'])
                else:names=[record['id']]
                for name in names:
                    container=self._app_container(record['id'],checked,service_key=name)
                    if container and container.get('State',{}).get('Running'):
                        targets['titan-'+name]=record['id'];memory_totals['titan-'+name]=cgroup_memory_details(container.get('State',{}).get('Pid'))
            except (Error,OSError,ValueError,KeyError,TypeError):continue
        result={record['id']:{'cpu_percent':0,'memory_bytes':0,'memory_cache_bytes':0,'memory_swap_bytes':0,'memory_limit_bytes':None,'oom_kills':0,'disk_read_bytes':None,'disk_write_bytes':None} for record in records}
        for app in targets.values():result[app].update(cpu_percent=None,memory_bytes=None)
        if targets:
            try:
                samples=parse_stats(_run(['docker','stats','--no-stream','--format','{{json .}}',*targets],timeout=15))
                for name,sample in samples.items():
                    details=memory_totals.get(name) or {}
                    for field in ('memory_bytes','memory_cache_bytes','memory_swap_bytes','memory_limit_bytes','oom_kills'):
                        sample[field]=details.get(field)
            except Error:return {'apps':result,'available':False}
            grouped={}
            for name,app in targets.items():grouped.setdefault(app,[]).append(samples.get(name))
            for app,samples in grouped.items():
                for field in result[app]:
                    values=[sample.get(field) if sample else None for sample in samples]
                    result[app][field]=sum(values) if all(value is not None for value in values) else None
        return {'apps':result,'available':True}


def cgroup_memory(pid, proc='/proc', cgroups='/sys/fs/cgroup'):
    """Actual cgroup v2 charge, including page cache (Docker CLI subtracts it)."""
    value=cgroup_memory_details(pid,proc,cgroups)
    return value.get('memory_bytes') if value else None


def cgroup_memory_details(pid, proc='/proc', cgroups='/sys/fs/cgroup'):
    """Read process-scoped cgroup counters; missing optional metrics stay null."""
    from pathlib import Path
    if type(pid) is not int or pid<=0:return None
    try:
        lines=(Path(proc)/str(pid)/'cgroup').read_text().splitlines()
        path=next(line[3:] for line in lines if line.startswith('0::'))
        if '..' in path.split('/') or not path.startswith('/'):return None
        root=Path(cgroups).resolve();directory=(root/path.lstrip('/')).resolve()
        if not directory.is_relative_to(root) or directory==root:return None
        def count(source):
            try:
                value=int((directory/source).read_text().strip())
                return value if 0<=value<=2**63-1 else None
            except (OSError,ValueError):return None
        current=count('memory.current')
        if current is None:return None
        def counters(source):
            try:
                values={key:int(value) for key,value in (line.split() for line in (directory/source).read_text().splitlines())}
                return values if all(0<=value<=2**63-1 for value in values.values()) else {}
            except (OSError,ValueError):return {}
        stats=counters('memory.stat');events=counters('memory.events')
        return {'memory_bytes':current,'memory_cache_bytes':stats.get('file'),
                'memory_anon_bytes':stats.get('anon'),'memory_swap_bytes':count('memory.swap.current'),
                'memory_limit_bytes':count('memory.max'),'oom_kills':events.get('oom_kill')}
    except (OSError,ValueError,StopIteration):return None
