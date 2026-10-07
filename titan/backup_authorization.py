"""Share-scoped delegated backup operations, checked again at the root boundary."""
from pathlib import PurePosixPath
from .core import Error

OPERATIONS={'backups','backup_settings','backup_create','backup_browse','backup_verify','backup_restore','backup_restore_selection'}


def readable(shares,user):
    return {share['name'] for share in shares if not share.get('blocked') and user in share.get('readers',[])+share.get('writers',[])}


def allowed_manifest(manifest,allowed):
    return isinstance(manifest,dict) and manifest.get('type')=='shares' and isinstance(manifest.get('shares'),list) and bool(manifest['shares']) and set(manifest['shares'])<=allowed


def safe_settings(settings,allowed):
    return {**settings,'shares':[name for name in settings.get('shares',[]) if name in allowed],
            'include_config':False,'apps':[],'app_data':[],'delegated':True,'configuration_editable':False}


def safe_listing(records,allowed):
    # Keep only complete share backups whose every source is visible to this user.
    return [{**manifest,'include_config':False,'configuration_available':False}
            for manifest in records if allowed_manifest(manifest,allowed)]


def authorize(operation,arguments,user,shares,manifest=None):
    if operation not in OPERATIONS or not isinstance(arguments,dict):raise Error('Ungültige delegierte Backupaktion.')
    fields={'backups':set(),'backup_settings':set(),'backup_create':{'shares','include_config'},'backup_verify':{'backup'},'backup_browse':{'backup','path','offset','limit'},'backup_restore':{'backup','share','name'},'backup_restore_selection':{'backup','paths','share','name'}}
    if set(arguments)-fields[operation]:raise Error('Unbekannte delegierte Backupoption.')
    allowed=readable(shares,user)
    if operation=='backup_create':
        names=arguments.get('shares')
        if set(arguments)-{'shares','include_config'} or not isinstance(names,list) or not names or any(not isinstance(name,str) for name in names) or not set(names)<=allowed or arguments.get('include_config') is not False:
            raise Error('Nur eigene lesbare Freigaben ohne NAS-Konfiguration dürfen gesichert werden.',403)
    elif operation not in ('backups','backup_settings'):
        if not allowed_manifest(manifest,allowed):raise Error('Kein Zugriff auf die Quellen dieser Sicherung.',403)
        if operation=='backup_browse':
            path=arguments.get('path','')
            if not isinstance(path,str) or '..' in PurePosixPath(path).parts or path.startswith('/') or (path and path.split('/')[0] not in allowed):raise Error('Kein Zugriff auf diesen Sicherungspfad.',403)
        if operation in ('backup_restore','backup_restore_selection'):
            target=next((share for share in shares if share['name']==arguments.get('share')),None)
            if not target or target.get('blocked') or user not in target.get('writers',[]):raise Error('Keine Schreibrechte auf der Zielfreigabe.',403)
            if operation=='backup_restore_selection':
                paths=arguments.get('paths')
                if not isinstance(paths,list) or not paths or any(not isinstance(path,str) or path.startswith('/') or '..' in PurePosixPath(path).parts or path.split('/')[0] not in allowed for path in paths):raise Error('Keine Leserechte auf die ausgewählten Sicherungsquellen.',403)
    return allowed


def host_call(host,operation,user,arguments):
    if operation not in OPERATIONS or not isinstance(arguments,dict):raise Error('Ungültige delegierte Backupaktion.')
    with host.account_lock:
        host.require_active_account(user)
        if user=='titan-files':raise Error('Dienstidentitäten erhalten keine delegierten Sicherungen.',403)
        shares=host.op_shares()
        manifest=host.backups.manifest(arguments.get('backup')) if operation not in ('backups','backup_settings','backup_create') else None
        allowed=authorize(operation,arguments,user,shares,manifest)
    if operation=='backups':return {'items':safe_listing(host.backups.list(),allowed),'delegated':True,'settings':safe_settings(host.backups.settings(),allowed)}
    if operation=='backup_settings':return safe_settings(host.backups.settings(),allowed)
    functions={'backup_create':host.backups.create,'backup_verify':host.backups.verify,'backup_browse':host.backups.browse,'backup_restore':host.backups.restore,'backup_restore_selection':host.backups.restore_selection}
    if operation == 'backup_create':
        arguments = {**arguments, 'apps': [], 'app_data': []}
    return functions[operation](**arguments)


def web_authorize(store, agent, user, operation, arguments):
    from .identity import require_application
    current = require_application(store, user, 'backups')
    shares = agent.call('shares')
    manifest = None
    if operation != 'backup_create':
        listing = agent.call('backups')
        records = listing.get('items', []) if isinstance(listing, dict) else listing
        manifest = next((record for record in records if record.get('id') == arguments.get('backup')), None)
    authorize(operation, arguments, current['system_user'], shares, manifest)
    return current
