"""Identity previews isolated to Demo's temporary directory and memory."""
import copy
import hashlib
from pathlib import Path
from .core import Error, identifier, integer
from .identity import APPLICATIONS, effective_share, empty_policy, validate_policy

IDENTITY_OPERATIONS = {'identity_capabilities', 'identity_baseline', 'identity_homes',
                       'identity_apply', 'identity_home', 'user_quotas', 'user_quota', 'delegated_backup'}


class DemoIdentityMixin:
    def op_delegated_backup(self, action, user, arguments):
        operation = action
        from .backup_authorization import authorize, safe_listing, safe_settings
        if not any(account['name']==user and account.get('enabled',True) and not account.get('removed') for account in self.accounts):
            raise Error('Demo-Benutzer ist gesperrt.',403)
        manifest=self.backup(arguments.get('backup')) if operation not in ('backups','backup_settings','backup_create') else None
        allowed=authorize(operation,arguments,user,self.shares,manifest)
        if operation=='backups':return {'items':safe_listing(self.backup_records,allowed),'delegated':True,'settings':safe_settings(self.backup_settings,allowed)}
        if operation=='backup_settings':return safe_settings(self.backup_settings,allowed)
        return self.call(operation,**arguments)

    def initialize_demo_identity(self):
        if hasattr(self, '_identity_policy'): return
        self._identity_policy=empty_policy();self._identity_baseline={};self._identity_homes={};self._identity_quotas={}
        self._identity_users=[]

    def op_identity_capabilities(self):
        self.initialize_demo_identity()
        return {'groups':True,'homes':True,'quota_backends':['zfs'],'applications':APPLICATIONS,
                'quota_notice':'Demo: ZFS-Quoten und Speicherverbrauch werden ausschließlich simuliert.'}

    def op_identity_baseline(self):
        self.initialize_demo_identity()
        names={share['name'] for share in self.shares}
        self._identity_baseline={name:value for name,value in self._identity_baseline.items() if name in names}
        for share in self.shares:
            self._identity_baseline.setdefault(share['name'],{'name':share['name'],'readers':list(share['readers']),'writers':list(share['writers'])})
        return copy.deepcopy(self._identity_baseline)

    def op_identity_homes(self):
        self.initialize_demo_identity();return copy.deepcopy(self._identity_homes)

    def op_identity_apply(self,policy,users):
        self.initialize_demo_identity()
        if not isinstance(users,list) or any(not isinstance(user,dict) or set(user)!={'name','system_user'} for user in users):
            raise Error('Ungültige Benutzerzuordnung.')
        known={account['name'] for account in self.accounts if not account.get('removed')}
        for user in users:
            identifier(user['name']);identifier(user['system_user'])
            if user['system_user']!='titan-files' and user['system_user'] not in known: raise Error('Unbekannte Demoidentität.')
        if len({user['name'] for user in users})!=len(users): raise Error('Doppelte Benutzerzuordnung.')
        policy=validate_policy(policy,users,self.shares)
        legacy={user['name'] for user in users if user['system_user']=='titan-files'}
        if any(name in legacy and item['shares'] for name,item in policy['users'].items()) or any(set(group['members'])&legacy and group['shares'] for group in policy['groups']):
            raise Error('Dienstidentitäten erhalten keine persönlichen Gruppenrechte.')
        private={home['share'] for home in self._identity_homes.values()}
        if any(set(group['shares'])&private for group in policy['groups']) or any(set(item['shares'])&private for item in policy['users'].values()):
            raise Error('Persönliche Ordner haben feste private Rechte.')
        baseline=self.op_identity_baseline();updated=[]
        for share in self.shares:
            mapped={user['system_user'] for user in users if user['system_user']!='titan-files'}
            readers=[member for member in baseline[share['name']]['readers'] if member not in mapped]
            writers=[member for member in baseline[share['name']]['writers'] if member not in mapped]
            owner=next((name for name,home in self._identity_homes.items() if home['share']==share['name']),None)
            if owner: readers,writers=[],[]
            for user in users:
                if user['system_user']=='titan-files': continue
                right='write' if owner==user['system_user'] else 'none' if owner else effective_share(policy,user['name'],baseline[share['name']],user['system_user'])['permission']
                if right=='write': writers.append(user['system_user'])
                elif right=='read': readers.append(user['system_user'])
            updated.append({**share,'readers':sorted(set(readers)-set(writers)),'writers':sorted(set(writers))})
        self.shares=updated;self._identity_policy=policy;self._identity_users=copy.deepcopy(users)
        return {'ok':True,'demo':True}

    def op_identity_home(self,name):
        self.initialize_demo_identity();name=identifier(name)
        if not any(account['name']==name and account.get('enabled',True) and not account.get('removed') for account in self.accounts):
            raise Error('Persönlicher Ordner benötigt ein aktives Demo-Konto.')
        if name not in self._identity_homes:
            share='home-'+name[:18]+'-'+hashlib.sha256(name.encode()).hexdigest()[:6]
            if any(item['name']==share for item in self.shares): raise Error('Der persönliche Freigabename existiert bereits.',409)
            path=self._private/'identity-homes'/name;path.mkdir(parents=True,exist_ok=False)
            self._share_paths[share]=path
            self.shares.append({'name':share,'path':str(path),'readers':[],'writers':[name]})
            self._identity_homes[name]={'share':share,'path':str(path),'user':name}
        return {'ok':True,**copy.deepcopy(self._identity_homes[name]),'demo':True}

    def op_user_quotas(self,name):
        self.initialize_demo_identity();name=identifier(name)
        if not any(account['name']==name and not account.get('removed') for account in self.accounts): raise Error('Demo-Benutzer nicht gefunden.',404)
        targets=[]
        for dataset in self.datasets:
            share=next((share for share in self.shares if share.get('dataset')==dataset['name'] or share['path']==dataset.get('mountpoint')),None)
            if not share: continue
            targets.append({'id':dataset['name'],'label':share['name'],'path':share['path'],'backend':'zfs','supported':True,'used_bytes':256*1024**2,'limit_bytes':self._identity_quotas.get(name,{}).get(dataset['name'],0)})
        return {'name':name,'targets':targets,'notice':'Demo: Verbrauch und Quoten werden simuliert. Es werden keine Hostquoten gesetzt.'}

    def op_user_quota(self,name,target,limit_bytes):
        if type(limit_bytes) is not int or not isinstance(target,str):raise Error('Ungültige Demoquote.')
        quota=self.op_user_quotas(name);limit=integer(limit_bytes,0,2**63-1)
        if target not in {item['id'] for item in quota['targets']}: raise Error('Demo-Quotenbereich nicht gefunden.')
        self._identity_quotas.setdefault(name,{})[target]=limit
        return {'ok':True,'quota':next(item for item in self.op_user_quotas(name)['targets'] if item['id']==target),'demo':True}

    def identity_demo_guard(self,operation,arguments):
        """Reject private home sharing before the existing Demo mutates ACLs."""
        self.initialize_demo_identity()
        if operation not in ('share_user_permission','share_update'):return
        owner=next((name for name,home in self._identity_homes.items() if home['share']==arguments.get('name')),None)
        if owner is None:return
        if operation=='share_user_permission':
            valid=arguments.get('permission')=='none' or arguments.get('user')==owner and arguments.get('permission')=='write'
        else:
            valid=arguments.get('readers')==[] and isinstance(arguments.get('writers'),list) and set(arguments['writers'])<={owner}
        if not valid:raise Error('Persönliche Ordner behalten private Eigentümerrechte.',403)

    def identity_demo_observe(self,operation,arguments):
        """Call after existing Demo account/share mutations; no host commands."""
        self.initialize_demo_identity()
        if operation in ('share_user_permission','share_update'):
            baseline=self.op_identity_baseline();name=arguments['name']
            if name not in baseline:return
            users=[arguments['user']] if operation=='share_user_permission' else [item['name'] for item in self.accounts if not item.get('removed')]
            share=next(item for item in self.shares if item['name']==name)
            for user in users:
                web_name=next((item['name'] for item in self._identity_users if item['system_user']==user),None)
                right=arguments['permission'] if operation=='share_user_permission' else 'write' if user in share['writers'] else 'read' if user in share['readers'] else 'none'
                if web_name is not None:
                    self._identity_policy['users'].setdefault(web_name,{'applications':{},'shares':{}})['shares'][name]=right
                for field in ('readers','writers'):baseline[name][field]=[member for member in baseline[name][field] if member!=user]
                if right=='write':baseline[name]['writers'].append(user)
                elif right=='read':baseline[name]['readers'].append(user)
            self._identity_baseline=baseline
        elif operation=='share_remove':
            name=arguments['name']
            for group in self._identity_policy['groups']: group['shares'].pop(name,None)
            for user in self._identity_policy['users'].values(): user['shares'].pop(name,None)
            self._identity_baseline.pop(name,None)
            self._identity_homes={user:home for user,home in self._identity_homes.items() if home['share']!=name}
        elif operation=='account_remove':
            name=arguments['name'];web_name=next((item['name'] for item in self._identity_users if item['system_user']==name),name)
            self._identity_policy['users'].pop(web_name,None)
            for group in self._identity_policy['groups']:group['members']=[member for member in group['members'] if member!=web_name]
            self._identity_users=[item for item in self._identity_users if item['system_user']!=name]
            self._identity_homes.pop(name,None);self._identity_quotas.pop(name,None)
            for share in self._identity_baseline.values():
                for field in ('readers','writers'):share[field]=[member for member in share[field] if member!=name]
