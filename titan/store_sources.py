"""Read public store metadata and translate supported single-container recipes.

No upstream Compose document is executed. Host paths, commands and privileges
never cross the adapter boundary. Unsupported templates are reported explicitly.
"""
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from .core import Error

LINUXSERVER = 'https://api.linuxserver.io/api/v1/images?include_config=true&include_deprecated=false'
PRESETS = [
    {'id': 'linuxserver', 'name': 'LinuxServer.io', 'url': LINUXSERVER, 'format': 'linuxserver', 'default': True},
    {'id': 'casaos', 'name': 'CasaOS · IceWhale', 'url': 'https://github.com/IceWhaleTech/CasaOS-AppStore', 'format': 'casaos'},
    {'id': 'bigbear', 'name': 'BigBear CasaOS', 'url': 'https://codeload.github.com/bigbeartechworld/big-bear-casaos/zip/refs/heads/master', 'format': 'casaos'},
    {'id': 'community-linuxserver', 'name': 'LinuxServer · Community CasaOS', 'url': 'https://codeload.github.com/WisdomSky/LinuxServer-AppStore/zip/refs/heads/main', 'format': 'casaos'},
]

def slug(value):
    name = re.sub('[^a-z0-9_-]', '-', str(value).lower()).strip('-')
    if not name or not name[0].isalpha(): name = 'app-' + name
    return name if len(name) <= 18 else name[:11] + '-' + hashlib.sha256(name.encode()).hexdigest()[:6]

def line(value, limit=500):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit] or 'App des ausgewählten Stores.'

def port(value):
    match = re.fullmatch(r'([0-9]{1,5})(?:/(tcp|udp))?', str(value))
    if not match or not 1 <= int(match[1]) <= 65535: raise ValueError('Portbereiche oder dynamische Ports')
    return int(match[1]), match[2] or 'tcp'

def login(name):
    return ('Diese importierte Vorlage hat noch keinen von Titan geprüften Standardzugang. Anmeldung und Ersteinrichtung stehen in der direkt verlinkten Anleitung des Herausgebers. ' + name)[:2000]

def linuxserver_document(data):
    items = data['data']['repositories']['linuxserver']
    if not isinstance(items, list) or len(items) > 500: raise ValueError('Ungültiger LinuxServer-Katalog')
    apps, skipped = [], []
    for item in items:
        name = item.get('name', '')
        try:
            if item.get('deprecated') or not item.get('stable'): raise ValueError('Kein stabiles Image')
            cfg = item.get('config') or {}
            for key in ('caps', 'devices', 'networking', 'hostname', 'security_opt', 'privileged', 'mac_address'):
                if cfg.get(key): raise ValueError('Besondere Host- oder Geräteanforderungen')
            if any(not row.get('optional') for row in cfg.get('custom', [])): raise ValueError('Zusätzliche Laufzeitoptionen erforderlich')
            ports = [row for row in cfg.get('ports', []) if not row.get('optional')]
            web = next((row for row in ports if port(row['internal'])[1] == 'tcp' and re.search(r'web|gui|http|interface', row.get('desc', ''), re.I)), None)
            if web is None: raise ValueError('Keine eindeutige Weboberfläche')
            target, _ = port(web['internal'])
            required = [row['path'] for row in cfg.get('volumes', []) if not row.get('optional') and row['path'] != '/config']
            if len(required) > 1: raise ValueError('Mehrere erforderliche Datenziele')
            if required and (not re.fullmatch(r'/[a-zA-Z0-9_/-]{1,80}', required[0]) or required[0].startswith(('/dev', '/proc', '/sys', '/etc', '/lib', '/var/run'))): raise ValueError('Hostabhängige Datenziele')
            settings = []
            for env in cfg.get('env_vars', []):
                key = env['name']
                if key in ('PUID','PGID','TZ') or env.get('optional'): continue
                secret = bool(re.search(r'password|secret|token|api.?key', key, re.I))
                settings.append({'env':key,'label':line(key,80),'default':'' if secret else str(env.get('value','')), 'secret':secret})
            extras = []
            for row in ports:
                if row is web: continue
                internal, protocol = port(row['internal']); external, _ = port(row['external'])
                extras.append({'target':internal,'published':max(1024, external),'protocol':protocol})
            apps.append({'id':slug(name),'name':name,'description':line(item.get('description')), 'image':'lscr.io/linuxserver/'+name+':latest',
                'port':target,'scheme':'https' if re.search(r'\bhttps\b',web.get('desc',''),re.I) and not re.search(r'\bhttp\b',web.get('desc',''),re.I) else 'http','default_port':max(8080,target),'mount':required[0] if required else None,'config_mount':any(row['path']=='/config' for row in cfg.get('volumes', [])),
                'documentation':'https://docs.linuxserver.io/images/docker-'+name+'/', 'login_note':login(name), 'settings':settings,'ports':extras})
        except (ValueError, KeyError, TypeError) as exc:
            skipped.append({'name':line(name,80),'reason':str(exc)})
    return {'schema':1,'name':'LinuxServer.io','apps':apps}, skipped

def localized(value):
    return value.get('de_DE') or value.get('en_US') or next(iter(value.values()), '') if isinstance(value,dict) else value

def casaos_document(raw, name):
    import yaml
    apps, skipped = [], []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = archive.infolist()
        if len(files) > 12000: raise ValueError('Zu viele Archiveinträge')
        total = sum(row.file_size for row in files)
        if total > 512 * 1024**2: raise ValueError('Archiv entpackt zu groß')
        for row in files:
            if not row.filename.endswith(('docker-compose.yml','docker-compose.yaml')): continue
            label = row.filename.split('/')[-2]
            try:
                if row.file_size > 128 * 1024: raise ValueError('Vorlage zu groß')
                source = archive.read(row)
                # Reject aliases; bounded YAML can still expand recursively.
                if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(source)): raise ValueError('YAML-Verweise nicht unterstützt')
                doc = yaml.safe_load(source)
                services = doc.get('services', {})
                if not isinstance(services,dict) or len(services)!=1: raise ValueError('Mehrere Container erforderlich')
                service = next(iter(services.values()))
                allowed = {'image','container_name','restart','environment','ports','volumes','labels','deploy','x-casaos','networks','cpu_shares','mem_limit'}
                if set(service)-allowed: raise ValueError('Zusätzliche Laufzeitoptionen erforderlich')
                if service.get('networks') or doc.get('networks'): raise ValueError('Eigene Compose-Netzwerke erforderlich')
                meta = doc.get('x-casaos', {})
                web, _ = port(meta.get('port_map',''))
                ports = []
                for mapping in service.get('ports', []):
                    if isinstance(mapping, str):
                        parts=mapping.split(':')
                        if len(parts)!=2: raise ValueError('Nicht unterstützte Portzuordnung')
                        published,_=port(parts[0]); target,protocol=port(parts[1])
                    elif isinstance(mapping,dict):
                        published,_=port(mapping['published']);target,_=port(mapping['target']);protocol=mapping.get('protocol','tcp')
                    else: raise ValueError('Ungültige Portzuordnung')
                    ports.append((published,target,protocol))
                primary=next((p for p in ports if p[0]==web and p[2]=='tcp'),None)
                if primary is None: raise ValueError('Kein eindeutiger Webport')
                targets=[]
                for mapping in service.get('volumes', []):
                    if isinstance(mapping,str):
                        parts=mapping.split(':')
                        if len(parts)!=2: raise ValueError('Besondere Volume-Optionen erforderlich')
                        source,target=parts
                    else:
                        if set(mapping)-{'type','source','target'} or mapping.get('type','bind')!='bind': raise ValueError('Besondere Volume-Optionen erforderlich')
                        source,target=mapping['source'],mapping['target']
                    if source.startswith(('/dev','/proc','/sys','/etc','/var/run','/run','/lib')): raise ValueError('Hostdateien erforderlich')
                    targets.append(target)
                extra=[target for target in targets if target!='/config']
                if len(extra)>1: raise ValueError('Mehrere erforderliche Datenziele')
                env=service.get('environment',{})
                if isinstance(env,list): env=dict(value.split('=',1) for value in env)
                settings=[]
                for key,value in env.items():
                    if key in ('PUID','PGID','TZ'): continue
                    secret=bool(re.search(r'password|secret|token|api.?key',key,re.I))
                    value='' if secret else str(value)
                    if '$' in value: raise ValueError('Dynamische Compose-Variablen erforderlich')
                    settings.append({'env':key,'label':line(key,80),'default':value,'secret':secret})
                image=service['image']
                if ':' not in image and '@' not in image: image+=':latest'
                title=line(localized(meta.get('title')) or label,80)
                apps.append({'id':slug(label),'name':title,'description':line(localized(meta.get('description'))),'image':image,
                    'port':primary[1],'scheme':'https' if meta.get('scheme') == 'https' else 'http','default_port':max(1024,web),'mount':extra[0] if extra else None,'config_mount':'/config' in targets,
                    'documentation':'https://github.com/'+name,'login_note':login(title),'settings':settings,
                    'ports':[{'target':p[1],'published':max(1024,p[0]),'protocol':p[2]} for p in ports if p!=primary]})
            except (ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
                skipped.append({'name':line(label,80),'reason':line(str(exc),200)})
    if not apps: raise ValueError('Keine kompatiblen Einzelcontainer-Vorlagen gefunden')
    return {'schema':1,'name':name.split('/')[-1],'apps':apps}, skipped

def download(url, limit):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): raise Error('Store-Weiterleitungen sind nicht erlaubt.')
    with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url,headers={'User-Agent':'Titan-AppStore/2'}),timeout=30) as response:
        raw=response.read(limit+1)
    if len(raw)>limit: raise Error('Store-Download überschreitet das Größenlimit.')
    return raw

def github_document(url):
    # Read only small deployment files; store artwork is never downloaded.
    from concurrent.futures import ThreadPoolExecutor
    repo = url.removeprefix('https://github.com/')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo): raise Error('GitHub-Store ungültig.')
    info = json.loads(download('https://api.github.com/repos/' + repo, 128*1024))
    branch = info['default_branch']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', branch): raise Error('Store-Branch nicht unterstützt.')
    tree = json.loads(download('https://api.github.com/repos/' + repo + '/git/trees/' + branch + '?recursive=1', 4*1024**2))
    if tree.get('truncated'): raise Error('Store-Verzeichnis ist zu groß.')
    paths = [row['path'] for row in tree['tree'] if row.get('type') == 'blob' and row['path'].endswith(('docker-compose.yml', 'docker-compose.yaml')) and '/Apps/' in '/' + row['path']]
    if not paths or len(paths) > 1000: raise Error('Store benötigt 1 bis 1000 App-Vorlagen.')
    def get(path):
        if not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or '..' in path.split('/'): raise Error('Unsicherer Vorlagenpfad.')
        return path, download('https://raw.githubusercontent.com/' + repo + '/' + branch + '/' + path, 128*1024)
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        total = 0
        with ThreadPoolExecutor(max_workers=6) as pool:
            for path, raw in pool.map(get, paths):
                total += len(raw)
                if total > 16*1024**2: raise Error('Store-Vorlagen überschreiten 16 MiB.')
                archive.writestr(path, raw)
    return casaos_document(content.getvalue(), repo)


def fetch_document(url):
    if url.startswith('https://github.com/'):
        return github_document(url)
    if url == LINUXSERVER:
        return linuxserver_document(json.loads(download(url,8*1024**2)))
    if url.startswith('https://codeload.github.com/'):
        match=re.fullmatch(r'https://codeload.github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/zip/refs/heads/[A-Za-z0-9_.-]+',url)
        if not match: raise Error('GitHub-Archiv-URL ist ungültig.')
        return casaos_document(download(url,96*1024**2),match[1])
    return json.loads(download(url,1024**2)), []
