"""Post-start setup for first-party packages; no user-supplied shell scripts."""
import ipaddress
import json
import re
import time
from .core import Error


def validate_host(value):
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if not re.fullmatch(r'(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value) or any(not part or len(part) > 63 or part.startswith('-') or part.endswith('-') for part in value.split('.')):
            raise Error('NAS-Adresse als IP oder Hostname ohne http://, Port oder Pfad angeben.') from None
        return value


def office_settings(options):
    host = validate_host(options['nas_host'])
    authority = '[' + host + ']' if ':' in host else host
    return {'DocumentServerUrl': 'http://' + authority + ':' + str(options['stack_port_eurooffice_80_tcp']) + '/',
            'DocumentServerInternalUrl': 'http://eurooffice/', 'StorageUrl': 'http://nextcloud/',
            'jwt_secret': options['office_secret'], 'jwt_header': 'AuthorizationJwt'}


# Read the shared secret from stdin, never argv, job output or a public record.
OFFICE_CONFIG = r'''
chdir('/var/www/html');
define('OC_CONSOLE', true);
require_once '/var/www/html/lib/base.php';
$values = json_decode(stream_get_contents(STDIN), true, 16, JSON_THROW_ON_ERROR);
$config = \OCP\Server::get(\OCP\IConfig::class);
$appConfig = \OCP\Server::get(\OCP\IAppConfig::class);
foreach ($values as $key => $value) { $appConfig->setValueString('eurooffice', $key, (string)$value, sensitive: $key === 'jwt_secret'); }
$config->setSystemValue('allow_local_remote_servers', true);
$domains = $config->getSystemValue('trusted_domains', []);
if (!in_array('nextcloud', $domains, true)) { $domains[] = 'nextcloud'; }
$config->setSystemValue('trusted_domains', $domains);
'''


def provision(host, app, run):
    if app != 'titan-nextcloud-office':
        return
    record = host.managed_app(app)
    if record.get('package_initialized'):
        return
    container = host._app_container(app, record)
    if not container or not container.get('Id'):
        raise Error('Nextcloud-Container ist noch nicht erreichbar. Starten erneut versuchen.', 503)
    base = ['docker', 'exec', '-i', '--user', 'www-data', container['Id'], 'php']
    if host._app_options(app).get('office_mode', 'enabled') == 'disabled':
        # The optional variant still configures its mandatory cron service.
        # Existing packages without the field retain their Office connection.
        run([*base, 'occ', 'background:cron'], timeout=30)
        _mark_initialized(host, app)
        return
    try:
        # app:install may already have succeeded in an interrupted previous run.
        installed = json.loads(run([*base, 'occ', 'app:list', '--output=json'], timeout=30))
        if 'eurooffice' not in installed.get('enabled', {}) and 'eurooffice' not in installed.get('disabled', {}):
            run([*base, 'occ', 'app:install', 'eurooffice'], timeout=300)
        elif 'eurooffice' not in installed.get('enabled', {}):
            run([*base, 'occ', 'app:enable', 'eurooffice'], timeout=60)
        run([*base, '-r', OFFICE_CONFIG], input=json.dumps(office_settings(host._app_options(app))), timeout=60)
        run([*base, 'occ', 'background:cron'], timeout=30)
        # Nextcloud 35 caches app configuration in web APCu for three seconds.
        # CLI APCu is separate: installing/enabling the connector and clearing
        # its CLI cache does not invalidate the live HTTP route/config cache.
        # Wait beyond that TTL before the engine's real HTTP download probe.
        time.sleep(4)
        for attempt in range(3):
            try:
                run([*base, 'occ', 'eurooffice:documentserver', '--check'], timeout=90)
                break
            except Error:
                if attempt == 2:
                    raise
                time.sleep(4)
    except (Error, ValueError, TypeError):
        # Upstream output can include the JWT configuration. Keep it out of jobs.
        raise Error('Nextcloud läuft, aber die Euro-Office-Verbindung konnte noch nicht vollständig eingerichtet werden. Internetzugang und App-Status prüfen, anschließend Starten erneut versuchen.', 503) from None
    _mark_initialized(host, app)


def _mark_initialized(host, app):
    if callable(getattr(type(host), '_app_patch_record', None)):
        host._app_patch_record(app, {'package_initialized': True})
    else:
        # Small standalone smoke fixtures retain their legacy Host interface.
        records = host.load('apps', [])
        for item in records:
            if item['id'] == app:
                item['package_initialized'] = True
        host.save('apps', records)
