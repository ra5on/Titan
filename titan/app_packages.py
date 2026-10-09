"""Titan's small, first-party package catalog; legacy recipes stay separate.

Images and dependency versions follow the upstream installation instructions.
Database credentials are generated once by the installer, never by rendering.
"""
import copy
import secrets
from .core import Error


def mount(slot, target):
    return {'slot': slot, 'target': target, 'readonly': False}


def port(target, published=None, protocol='tcp'):
    return {'target': target, 'published': published or target, 'protocol': protocol}


def secret(key, label, generated=False):
    return {'key': key, 'label': label, 'type': 'password', 'required': not generated,
            'min_length': 16 if generated else 12, 'max_length': 128, **({'generated': True} if generated else {})}


def number(key, label, default, minimum=1024):
    return {'key': key, 'label': label, 'type': 'number', 'default': default,
            'min': minimum, 'max': 65535, 'required': True}


def text(key, label, default, pattern=None):
    return {'key': key, 'label': label, 'type': 'text', 'default': default,
            'required': True, 'min_length': 1, 'max_length': 253, **({'pattern': pattern} if pattern else {})}


def recipe(name, category, description, primary, services, webport, default_port, memory, schema, documentation, login, **extra):
    return {'name': name, 'category': category, 'description': description, 'image': services[primary]['image'],
            'port': webport, 'default_port': default_port, 'memory': memory, 'mount': None, 'scheme': 'http',
            'color': '#2788cf', 'symbol': name[0], 'titan_package': True, 'store_name': 'Titan AppStore',
            'catalog_status': 'available', 'documentation': documentation, 'install_schema': schema,
            'stack': {'primary': primary, 'services': services}, 'dependencies': [{'immich-server':'Immich · Fotos und Videos', 'immich-machine-learning':'Immich · Bilderkennung', 'database':'PostgreSQL · Datenbank', 'redis':'Cache-Dienst', 'nextcloud':'Nextcloud · Dateien', 'cron':'Hintergrundaufgaben', 'eurooffice':'Euro-Office · Dokumentbearbeitung', 'office-init':'Office-Ersteinrichtung', 'adguard':'AdGuard Home', 'pihole':'Pi-hole', 'tailscale':'Tailscale · privater Netzwerkzugang'}.get(key,key) for key in services],
            'first_login': {'mode': 'install' if any(f['type'] == 'password' and not f.get('generated') for f in schema) else 'setup',
                            'instructions': login, 'documentation': documentation, 'verified': '2026-10-04'}, **extra}


IMMICH_ENV = {'DB_HOSTNAME': 'database', 'DB_USERNAME': 'immich', 'DB_DATABASE_NAME': 'immich',
              'DB_PASSWORD': '@option:database_password', 'REDIS_HOSTNAME': 'redis',
              'IMMICH_MACHINE_LEARNING_URL': 'http://immich-machine-learning:3003', 'TZ': 'Europe/Berlin'}
NC_ENV = {'POSTGRES_HOST': 'database', 'POSTGRES_DB': 'nextcloud', 'POSTGRES_USER': 'nextcloud',
          'POSTGRES_PASSWORD': '@option:database_password', 'REDIS_HOST': 'redis',
          'NEXTCLOUD_ADMIN_USER': '@option:username', 'NEXTCLOUD_ADMIN_PASSWORD': '@option:password',
          'NEXTCLOUD_TRUSTED_DOMAINS': '@option:nas_host', 'TZ': 'Europe/Berlin'}
NC_MOUNTS = [mount('nextcloud', '/var/www/html'), mount('data', '/var/www/html/data')]

PACKAGES = {
 'titan-immich': recipe('Immich', 'Fotos', 'Fotos und Videos sichern, durchsuchen und teilen. Datenbank, Cache und Bilderkennung werden mitinstalliert.',
  'immich-server', {
   'immich-server': {'image': 'ghcr.io/immich-app/immich-server:v3.3.0@sha256:be56bc12c17a84617a979ad1eab1d9105bbec1955ffa7da09b3f9cf79d3bd09d', 'environment': IMMICH_ENV,
                    'mounts': [mount('data', '/data')], 'ports': [port(2283)],
                    'depends_on': {'database': {'condition': 'service_healthy'}, 'redis': {'condition': 'service_healthy'}}},
   'immich-machine-learning': {'image': 'ghcr.io/immich-app/immich-machine-learning:v3.3.0@sha256:aa88ec3aef3bdc97ab31eff66acecc98bb6ee14d47b6122c25e761ed9f31a7da', 'mounts': [mount('models', '/cache')]},
   'redis': {'image': 'docker.io/valkey/valkey:9@sha256:c123e3715db63d06d4ad6964884037aa0d5d4d703939b9929954112889708e1d',
             'memory': '512m', 'healthcheck': {'test': ['CMD', 'redis-cli', 'ping'], 'interval': '10s', 'timeout': '5s', 'retries': 10}},
   'database': {'image': 'ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:bcf63357191b76a916ae5eb93464d65c07511da41e3bf7a8416db519b40b1c23',
                'environment': {'POSTGRES_USER': 'immich', 'POSTGRES_DB': 'immich', 'POSTGRES_PASSWORD': '@option:database_password', 'POSTGRES_INITDB_ARGS': '--data-checksums'},
                'mounts': [mount('database', '/var/lib/postgresql/data')], 'shm_size': '128m', 'memory': '2g',
                'healthcheck': {'test': ['CMD', 'pg_isready', '-U', 'immich', '-d', 'immich'], 'interval': '10s', 'timeout': '5s', 'start_period': '30s', 'retries': 20}}
  }, 2283, 2283, '4g', [secret('database_password', 'Datenbankpasswort', True)],
  'https://docs.immich.app/install/docker-compose/', 'Beim ersten Öffnen dein eigenes Administratorkonto erstellen. Die Datenbank ist bereits verbunden; dafür sind keine Eingaben nötig.',
  note='16 GiB NAS-RAM für den vollständigen Verbund empfohlen; 8 GiB benötigen ausreichend freie Kapazität. Titan prüft das gesamte RAM-Budget vor dem Download. Fotos, Modelle und Datenbank liegen getrennt auf dem gewählten lokalen Speicher; Sicherung vor jedem Update erstellen. Ältere x86-Prozessoren ohne x86-64-v2 werden nicht unterstützt.'),
 'titan-adguard': recipe('AdGuard Home', 'Netzwerk', 'Werbung und Tracking im Heimnetz per DNS filtern.', 'adguard', {
   'adguard': {'image': 'adguard/adguardhome:v0.107.79@sha256:aba9e3bf0613be3ba3755e1fc311b126e2c24bec25e18b6483894a88283074f0', 'mounts': [mount('work', '/opt/adguardhome/work'), mount('config', '/opt/adguardhome/conf')],
               'ports': [port(3000), port(53, protocol='tcp'), port(53, protocol='udp')],
               'healthcheck': {'test': ['CMD', 'wget', '-q', '--spider', 'http://127.0.0.1:3000/'], 'interval': '15s', 'timeout': '5s', 'start_period': '10s', 'retries': 12}}
  }, 3000, 3000, '512m', [], 'https://github.com/AdguardTeam/AdGuardHome/wiki/Docker',
  'Im ersten Assistenten Benutzername und Passwort wählen. Für die Weboberfläche „Alle Schnittstellen“ und internen Port 3000 beibehalten, für DNS Port 53. Danach im Router die NAS-IP als DNS-Server eintragen.',
  note='DNS benötigt Port 53/TCP und UDP. AdGuard und Pi-hole können diesen Port auf derselben NAS-IP nicht gleichzeitig verwenden.'),
 'titan-jellyfin': recipe('Jellyfin', 'Medien', 'Filme, Serien, Musik und Fotos auf dem NAS verwalten und auf Fernseher, Handy und Browser streamen.', 'jellyfin', {
   'jellyfin': {'image': 'jellyfin/jellyfin:12.2@sha256:357724bf0ae27a672c7cbaa899db2d9abeb13dbd8657ccce750258a4c059d037', 'environment': {'TZ': 'Europe/Berlin'},
               'mounts': [mount('config', '/config'), mount('cache', '/cache'), mount('data', '/media')], 'ports': [port(8096)],
               'healthcheck': {'test': ['CMD-SHELL', 'curl -fsS http://127.0.0.1:8096/health | grep -q Healthy'], 'interval': '15s', 'timeout': '5s', 'start_period': '30s', 'retries': 12}}
  }, 8096, 8096, '2g', [], 'https://jellyfin.org/docs/general/installation/container/',
  'Beim ersten Öffnen im Assistenten Sprache und eigenes Administratorkonto wählen. Danach unter „Bibliotheken“ den Ordner /media hinzufügen; dort liegen die Dateien des gewählten Speichers.',
  note='Medien liegen im gewählten Speicher unter /media und werden von Jellyfin nur gelesen und katalogisiert. Hardware-Transkodierung wird nicht automatisch eingerichtet; ohne sie wandelt die CPU um, was bei mehreren gleichzeitigen Streams viel Leistung braucht.'),
 'titan-pihole': recipe('Pi-hole', 'Netzwerk', 'DNS-Werbeblocker mit eigenen Filterlisten und Statistiken.', 'pihole', {
   'pihole': {'image': 'pihole/pihole:2026.09.0', 'environment': {'TZ': 'Europe/Berlin', 'FTLCONF_webserver_api_password': '@option:password', 'FTLCONF_dns_listeningMode': 'ALL'},
             'mounts': [mount('config', '/etc/pihole')], 'ports': [port(80), port(53, protocol='tcp'), port(53, protocol='udp')]}
  }, 80, 8082, '512m', [secret('password', 'Pi-hole Web-Passwort')], 'https://docs.pi-hole.net/docker/',
  'Unter /admin mit dem hier gewählten Web-Passwort anmelden. Ein Benutzername ist nicht erforderlich. Danach im Router die NAS-IP als DNS-Server eintragen.',
  note='DNS benötigt Port 53/TCP und UDP. AdGuard und Pi-hole können diesen Port auf derselben NAS-IP nicht gleichzeitig verwenden. DHCP ist standardmäßig deaktiviert.'),
 'titan-nextcloud-office': recipe('Nextcloud + Euro-Office', 'Dateien', 'Private Cloud und Dokumentbearbeitung mit automatisch eingerichteter Datenbank, Cache und Euro-Office.', 'nextcloud', {
   'nextcloud': {'image': 'nextcloud:35-apache', 'environment': NC_ENV, 'mounts': NC_MOUNTS, 'ports': [port(80)],
                 'depends_on': {'database': {'condition': 'service_healthy'}, 'redis': {'condition': 'service_healthy'}},
                 'memory': '2g', 'healthcheck': {'test': ['CMD-SHELL', "curl -fsS http://localhost/status.php | grep -q '\"installed\":true'"], 'interval': '10s', 'timeout': '5s', 'start_period': '60s', 'retries': 20}},
   'cron': {'image': 'nextcloud:35-apache', 'environment': NC_ENV, 'mounts': NC_MOUNTS, 'entrypoint': ['/cron.sh'], 'memory': '512m',
            'depends_on': {'nextcloud': {'condition': 'service_healthy'}}},
   'database': {'image': 'postgres:17-alpine', 'environment': {'POSTGRES_DB': 'nextcloud', 'POSTGRES_USER': 'nextcloud', 'POSTGRES_PASSWORD': '@option:database_password'},
                'mounts': [mount('database', '/var/lib/postgresql/data')], 'memory': '1g',
                'healthcheck': {'test': ['CMD', 'pg_isready', '-U', 'nextcloud', '-d', 'nextcloud'], 'interval': '10s', 'timeout': '5s', 'retries': 20}},
   'redis': {'image': 'redis:7-alpine', 'memory': '256m', 'healthcheck': {'test': ['CMD', 'redis-cli', 'ping'], 'interval': '10s', 'timeout': '5s', 'retries': 10}},
   'office-init': {'image': 'ghcr.io/euro-office/documentserver:v9.3.4-hotfix.1', 'memory': '512m',
                  'entrypoint': ['/bin/sh', '-ec'], 'command': ['cp -a --update=none /etc/euro-office/documentserver/. /titan-seed/config/; cp -a --update=none /var/lib/euro-office/documentserver/. /titan-seed/data/; cp -a --update=none /var/log/euro-office/documentserver/. /titan-seed/logs/; chown -R ds:ds /titan-seed/data /titan-seed/logs'],
                  'mounts': [mount('office-config', '/titan-seed/config'), mount('office-data', '/titan-seed/data'), mount('office-logs', '/titan-seed/logs')]},
   'eurooffice': {'image': 'ghcr.io/euro-office/documentserver:v9.3.4-hotfix.1', 'memory': '4g',
                  'depends_on': {'office-init': {'condition': 'service_completed_successfully'}},
                  'environment': {'JWT_ENABLED': 'true', 'JWT_HEADER': 'AuthorizationJwt', 'JWT_SECRET': '@option:office_secret', 'ALLOW_PRIVATE_IP_ADDRESS': 'true'},
                  'mounts': [mount('office-data', '/var/lib/euro-office/documentserver'), mount('office-private', '/var/www/euro-office/Data'), mount('office-logs', '/var/log/euro-office/documentserver'), mount('office-config', '/etc/euro-office/documentserver')],
                  'ports': [port(80, 9980)], 'healthcheck': {'test': ['CMD-SHELL', 'curl -fsS http://localhost/healthcheck | grep -q true'], 'interval': '15s', 'timeout': '10s', 'start_period': '60s', 'retries': 20}}
  }, 80, 8088, '2g', [text('username', 'Nextcloud Administrator', 'admin', '[A-Za-z0-9_.@-]{1,64}'), secret('password', 'Nextcloud Admin-Passwort'),
      text('nas_host', 'NAS-IP oder Hostname', 'titan.local', '[A-Za-z0-9][A-Za-z0-9.:-]{0,252}'),
      secret('database_password', 'Datenbankpasswort', True), secret('office_secret', 'Office-Verbindungsschlüssel', True)],
  'https://docs.nextcloud.com/server/stable/admin_manual/office/euro-office/',
  'Mit dem hier gewählten Nextcloud-Administrator und Passwort anmelden. Dokumente in Nextcloud öffnen: Euro-Office ist bereits verbunden. Vorhandene Nextcloud-Daten behalten ihre bisherigen Konten.',
  note='Mindestens 8 GB freier Arbeitsspeicher empfohlen. Nextcloud und Office werden lokal über HTTP angeboten; für Internetzugriff beide Dienste hinter einem HTTPS-Reverse-Proxy betreiben.', provision='nextcloud-office')
}

PACKAGES['titan-cloudflared'] = recipe('Cloudflare Tunnel', 'Netzwerk',
    'Dein NAS über Cloudflare erreichen. Als eigene Compose-App mit sichtbaren Installationsschritten.',
    'cloudflared', {'cloudflared': {
        'image': 'cloudflare/cloudflared:2026.10.0@sha256:9b49eed8f62806d5d45ddf59ecefb5710429598ea6d3fcccd2af938f621b2b07',
        'command': ['tunnel', '--no-autoupdate', '--metrics', '127.0.0.1:5103', 'run', '--token-file', '/etc/cloudflared/token'],
        'mounts': [{'slot': 'credentials', 'target': '/etc/cloudflared', 'readonly': True}],
        'user': '0:0', 'read_only': True, 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true']
    }}, 0, 0, '256m', [{'key': 'tunnel_token', 'label': 'Cloudflare Tunnel-Token', 'type': 'password',
        'required': True, 'min_length': 80, 'max_length': 4096, 'pattern': '[A-Za-z0-9+/]+={0,2}',
        'help': 'Nur den Tunnel-Token (eyJ…) einfügen. Wird ausschließlich in privaten App-Dateien gespeichert.'}],
    'https://developers.cloudflare.com/tunnel/get-started/',
    'Kein zusätzliches Passwort. Titan-Anmeldung und deren Sicherheitsregeln bleiben erhalten. Tunnel-Token im Apps-Bereich einrichten oder ersetzen.',
    web_available=False, default_network='host',
    note='Kein eigener Webport. HTTP-Ziel für die öffentliche Titan-Route: http://127.0.0.1:5102. Die öffentliche Route im Cloudflare-Konto einrichten; ein Tunnel-Token kann DNS und Routen nicht bearbeiten.')

PACKAGES['titan-tailscale'] = recipe('Tailscale', 'Netzwerk',
    'Dein NAS und ausdrücklich gewählte Heimnetzbereiche privat über Tailscale erreichen.',
    'tailscale', {'tailscale': {
        'image': 'tailscale/tailscale:v1.102.5@sha256:c507f3a2a6ab1cabd8d809b98edeb41edbd5c3fb6ad9632ffd098b4c7d0b4065',
        'environment': {'TS_STATE_DIR': '/var/lib/tailscale', 'TS_AUTH_ONCE': 'true', 'TS_USERSPACE': 'true',
            'TS_ACCEPT_DNS': 'false', 'TS_AUTHKEY': 'file:/etc/titan-tailscale/authkey',
            'TS_HOSTNAME': '@option:hostname', 'TS_ROUTES': '@option:subnet_routes'},
        'mounts': [mount('state', '/var/lib/tailscale'), {'slot': 'credentials', 'target': '/etc/titan-tailscale', 'readonly': True}],
        'user': '0:0', 'security_opt': ['no-new-privileges:true'],
        'healthcheck': {'test': ['CMD-SHELL', 'tailscale status --json | grep -q \'"BackendState": "Running"\''],
            'interval': '10s', 'timeout': '5s', 'start_period': '20s', 'retries': 12}
    }}, 0, 0, '256m', [secret('auth_key', 'Tailscale Auth-Key'),
        text('hostname', 'Gerätename', 'titan', '[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'),
        {'key': 'nas_address', 'label': 'NAS-IP zusätzlich freigeben', 'type': 'text', 'default': '', 'required': False,
         'min_length': 0, 'max_length': 45, 'help': 'Optional: private NAS-IP als einzelne Hostroute ankündigen. Nach Freigabe im Tailscale-Konto über diese private IP erreichbar.'},
        {'key': 'subnet_routing', 'label': 'Heimnetz freigeben', 'type': 'text', 'default': 'disabled', 'required': True,
         'min_length': 7, 'max_length': 8, 'pattern': '(?:enabled|disabled)', 'choices': [['disabled', 'Deaktiviert'], ['enabled', 'Gewählte Bereiche freigeben']]},
        {'key': 'subnet_routes', 'label': 'Freigegebene Heimnetzbereiche', 'type': 'text', 'default': '', 'required': False,
         'min_length': 0, 'max_length': 512, 'help': 'Private CIDR-Bereiche, mit Komma getrennt, z. B. 192.168.1.0/24. Danach im Tailscale-Konto freigeben.'}],
    'https://tailscale.com/docs/features/containers/docker/docker-params',
    'Auth-Key im Tailscale-Konto erstellen. Gewählte Subnet-Routen anschließend in der Tailscale-Verwaltung freigeben und passende Zugriffsregeln erlauben. Diese Freigabe wird von Titan nicht automatisch vorgenommen.',
    web_available=False, note='Isolierter Userspace-Router für TCP und UDP; Ping eingeschränkt, andere IP-Protokolle nicht unterstützt. Verändert weder Host-IP-Forwarding noch Host-Firewall oder Host-DNS. Ohne NAS-IP oder freigegebene Routen werden keine NAS-Dienste bereitgestellt.')

# Every secondary publication is editable before installation and registered for
# conflict checks. DNS TCP and UDP default to the same host port on separate protocols.
for package in PACKAGES.values():
    package['extra_ports'] = []
    for name, service in package['stack']['services'].items():
        for mapping in service.get('ports', []):
            if name == package['stack']['primary'] and mapping['target'] == package['port'] and mapping['protocol'] == 'tcp':
                continue
            key = 'stack_port_' + name + '_' + str(mapping['target']) + '_' + mapping['protocol']
            package['install_schema'].append(number(key, ('DNS' if mapping['target'] == 53 else 'Euro-Office') + ' · Port ' + mapping['protocol'].upper(), mapping['published'], 1 if mapping['target'] == 53 else 1024))
            package['extra_ports'].append({'option': key, 'target': mapping['target'], 'protocol': mapping['protocol'], 'service': name})


def prepare_options(app, options, previous=None):
    result = dict(options or {})
    if app in PACKAGES:
        # Defaults in the validation schema preserve installed 0.5.0 packages.
        # Only a fresh installation opts into the new bounded resource profile.
        result.setdefault('resource_profile', (previous or {}).get('resource_profile', 'legacy' if previous else 'balanced'))
    if app == 'titan-nextcloud-office':
        result.setdefault('office_mode', (previous or {}).get('office_mode', 'enabled' if previous else 'disabled'))
    for field in PACKAGES.get(app, {}).get('install_schema', []):
        if field.get('generated'):
            result[field['key']] = (previous or {}).get(field['key']) or secrets.token_hex(32)
    return result


RESOURCE_PROFILES = {
    'balanced': {'label': 'Ausgewogen', 'help': 'Begrenzte Parallelität für ein privates NAS. Titan prüft vor dem Start eine RAM-Reserve.'},
    'performance': {'label': 'Mehr Parallelität', 'help': 'Größere Obergrenzen; benötigt mehr verfügbaren Arbeitsspeicher.'},
    'legacy': {'label': 'Bisherige Installation', 'help': 'Gespeicherte Bestandskonfiguration; wird nicht automatisch verändert.'},
}

# These are cgroup ceilings, never a claim about measured consumption. Office's
# upstream minimum is 4 GiB; shrinking that ceiling hides OOM failures rather
# than making an 8 GiB NAS a safe full-stack Office host.
RESOURCE_LIMITS = {
    'titan-immich': {
        'balanced': {'immich-server': '2g', 'immich-machine-learning': '2g', 'database': '2g', 'redis': '256m'},
        'performance': {'immich-server': '4g', 'immich-machine-learning': '4g', 'database': '2g', 'redis': '512m'},
    },
    'titan-nextcloud-office': {
        'balanced': {'nextcloud': '2g', 'cron': '768m', 'database': '768m', 'redis': '256m', 'office-init': '512m', 'eurooffice': '4g'},
        'performance': {'nextcloud': '4g', 'cron': '1g', 'database': '1536m', 'redis': '512m', 'office-init': '512m', 'eurooffice': '4g'},
    },
    'titan-adguard': {'balanced': {'adguard': '512m'}, 'performance': {'adguard': '512m'}},
    'titan-jellyfin': {'balanced': {'jellyfin': '2g'}, 'performance': {'jellyfin': '4g'}},
    'titan-pihole': {'balanced': {'pihole': '512m'}, 'performance': {'pihole': '512m'}},
    'titan-cloudflared': {'balanced': {'cloudflared': '256m'}, 'performance': {'cloudflared': '256m'}},
    'titan-tailscale': {'balanced': {'tailscale': '256m'}, 'performance': {'tailscale': '512m'}},
}

for package in PACKAGES.values():
    package['install_schema'].append({'key': 'resource_profile', 'label': 'RAM-Profil', 'type': 'text',
        'default': 'legacy', 'display_default': 'balanced', 'required': True, 'min_length': 6, 'max_length': 11,
        'pattern': '(?:balanced|performance|legacy)',
        'choices': [[key, item['label']] for key, item in RESOURCE_PROFILES.items()],
        'help': 'Containergrenzen sind Obergrenzen, kein reservierter oder gemessener RAM-Verbrauch.'})
PACKAGES['titan-nextcloud-office']['install_schema'].append({'key': 'office_mode', 'label': 'Dokumentbearbeitung', 'type': 'text',
    'default': 'enabled', 'display_default': 'disabled', 'required': True, 'min_length': 7, 'max_length': 8,
    'pattern': '(?:enabled|disabled)', 'choices': [['disabled', 'Nextcloud ohne Office'], ['enabled', 'Euro-Office mitinstallieren']],
    'help': 'Datenbank, Cache und Hintergrundaufgaben werden immer eingerichtet. Office benötigt zusätzlich mindestens 4 GiB RAM.'})
PACKAGES['titan-nextcloud-office']['name'] = 'Nextcloud'
PACKAGES['titan-nextcloud-office']['description'] = 'Private Cloud mit Datenbank, Cache und Hintergrundaufgaben. Dokumentbearbeitung mit Euro-Office optional.'
PACKAGES['titan-nextcloud-office']['note'] = 'Vor Download und Start prüft Titan das RAM-Budget einschließlich NAS-Reserve. Euro-Office benötigt zusätzlich mindestens 4 GiB. Für Internetzugriff HTTPS einrichten.'
PACKAGES['titan-nextcloud-office']['first_login']['instructions'] = 'Mit dem hier gewählten Nextcloud-Administrator und Passwort anmelden. Euro-Office wird verbunden, wenn du es mitinstallierst. Vorhandene Daten behalten ihre bisherigen Konten.'

# Explicit persistence also avoids untracked anonymous image VOLUMEs. Older
# installs remain readable through their saved, verified Compose definition.
PACKAGES['titan-immich']['stack']['services']['redis']['mounts'] = [mount('redis', '/data')]
PACKAGES['titan-nextcloud-office']['stack']['services']['redis']['mounts'] = [mount('redis', '/data')]


def selected_recipe(app, recipe, options):
    """Resolve bounded, explicit variants without modifying the shared catalog."""
    if app not in PACKAGES:
        return recipe
    result = copy.deepcopy(recipe)
    if app == 'titan-tailscale':
        from .native_apps import advertised_routes
        result['stack']['services']['tailscale']['environment']['TS_ROUTES'] = advertised_routes(options)
    profile = options.get('resource_profile', 'legacy')
    if profile not in RESOURCE_PROFILES:
        raise Error('Ungültiges RAM-Profil.')
    office = options.get('office_mode', 'enabled')
    if app == 'titan-nextcloud-office' and office not in ('enabled', 'disabled'):
        raise Error('Ungültige Auswahl für Dokumentbearbeitung.')
    if app == 'titan-nextcloud-office' and office == 'disabled':
        for key in ('office-init', 'eurooffice'):
            result['stack']['services'].pop(key, None)
        result['extra_ports'] = [item for item in result.get('extra_ports', []) if item.get('service') != 'eurooffice']
    if profile != 'legacy':
        services = result['stack']['services']
        for name, service in services.items():
            service['memory'] = RESOURCE_LIMITS[app][profile][name]
        if app == 'titan-nextcloud-office':
            # Nextcloud's supported per-request PHP minimum stays at 512 MiB.
            # Bound Apache's prefork workers instead of truncating PHP requests.
            workers = 3 if profile == 'balanced' else 6
            services['nextcloud']['environment']['PHP_MEMORY_LIMIT'] = '512M'
            services['cron']['environment']['PHP_MEMORY_LIMIT'] = '512M'
            apache = ('<IfModule mpm_prefork_module>\nStartServers 1\nMinSpareServers 1\nMaxSpareServers 2\n'
                      f'ServerLimit {workers}\nMaxRequestWorkers {workers}\nMaxConnectionsPerChild 500\n</IfModule>\n')
            services['nextcloud']['entrypoint'] = ['/bin/sh', '-ec']
            services['nextcloud']['command'] = ["printf '%s' '" + apache + "' > /etc/apache2/mods-available/mpm_prefork.conf; exec /entrypoint.sh apache2-foreground"]
            services['database']['command'] = ['postgres', '-c', 'shared_buffers=128MB' if profile == 'balanced' else 'shared_buffers=256MB',
                '-c', 'work_mem=4MB', '-c', 'maintenance_work_mem=64MB', '-c', 'max_connections=30' if profile == 'balanced' else 'max_connections=50']
            services['redis']['command'] = ['redis-server', '--maxmemory', '128mb' if profile == 'balanced' else '256mb', '--maxmemory-policy', 'noeviction']
        if app == 'titan-immich':
            # Leave the vector database's upstream configuration intact. Limit
            # concurrent ML workers instead of making model loads silently fail.
            services['immich-machine-learning'].setdefault('environment', {})['MACHINE_LEARNING_WORKERS'] = '1'
    return result
