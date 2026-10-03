from titan import debian_updates

def identity(version='0.0.0',stage='alpha'):
    return {'format':debian_updates.FORMAT,'platform':'debian-rauc','compatible':debian_updates.COMPATIBLE,
            'architecture':'x86_64','state_schema':1,'release_id':'sha256:'+'a'*64,
            'version':version,'release_stage':stage,
            'system_accounts':{'users':{'root':{'uid':0,'gid':0}},'groups':{'root':0}}}

def manifest(version,stage):
    return {**identity(version,stage),'boot_test':'passed','runtime_test':'passed','update_test':'passed','rollback_test':'passed',
            'rootfs_sha256':'b'*64,'bundle':{'name':'titan-test-amd64.raucb','size':1024,'sha256':'c'*64}}

def state(version='0.0.0'):
    return {'current':version,'current_stage':'alpha','health_confirmed':True,'reboot_required':False,'reboot_scheduled':False,
            'booted':{'slot':'A'}}
