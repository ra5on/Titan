"""Explicit character-device passthrough for apps, never privileged containers."""
import re
import stat
import json
import shutil
import subprocess
from pathlib import Path
from .core import Error


def devices(root='/dev'):
    base=Path(root); result=[]; seen=set()
    for pattern,kind in [('serial/by-id/*','usb'),('ttyUSB*','usb'),('ttyACM*','usb'),('bus/usb/*/*','usb'),('dri/renderD*','gpu')]:
        for path in sorted(base.glob(pattern)):
            try:
                real=path.resolve(strict=True); metadata=real.stat()
                if not real.is_relative_to(base.resolve()) or not stat.S_ISCHR(metadata.st_mode) or metadata.st_rdev in seen: continue
                seen.add(metadata.st_rdev)
                result.append({'id':str(path), 'path':str(real),'label':path.name,'kind':kind,'group':metadata.st_gid})
            except OSError: continue
    if root=='/dev' and shutil.which('nvidia-smi') and shutil.which('nvidia-container-runtime'):
        try:
            info=subprocess.run(['docker','info','--format','{{json .Runtimes}}'],capture_output=True,text=True,timeout=5,check=True)
            if 'nvidia' in json.loads(info.stdout):
                query=subprocess.run(['nvidia-smi','--query-gpu=uuid,name','--format=csv,noheader'],capture_output=True,text=True,timeout=5,check=True)
                for row in query.stdout.splitlines()[:16]:
                    identifier,_,label=row.partition(',')
                    if re.fullmatch(r'GPU-[a-fA-F0-9-]{36}',identifier.strip()): result.append({'id':'nvidia:'+identifier.strip(),'path':None,'label':label.strip(),'kind':'gpu','group':None,'driver':'nvidia'})
        except (OSError,ValueError,subprocess.SubprocessError): pass
    return result[:64]


def validate(value, inventory=None):
    if value is None: return []
    if not isinstance(value,list) or len(value)>16 or any(not isinstance(item,str) for item in value) or len(set(value))!=len(value): raise Error('Maximal 16 unterschiedliche App-Geräte auswählen.')
    found={item['id']:item for item in devices() if item['kind'] in ('usb','gpu')} if inventory is None else {item['id']:item for item in inventory}
    if any(item not in found for item in value): raise Error('Ausgewähltes USB/GPU-Gerät ist nicht mehr verfügbar.',409)
    return value


def apply(definition, app, value, inventory=None):
    if not value: return definition
    if all(isinstance(item,dict) for item in value):
        inventory=value
        for item in value:
            if set(item)-{'id','path','label','kind','group','driver'} or item.get('kind') not in ('usb','gpu') or not isinstance(item.get('id'),str): raise Error('Ungültige gespeicherte App-Geräte.')
            if item.get('driver')=='nvidia':
                if not re.fullmatch(r'nvidia:GPU-[a-fA-F0-9-]{36}',item['id']): raise Error('Ungültige GPU-ID.')
            elif not isinstance(item.get('path'),str) or not re.fullmatch(r'/dev/(?:ttyUSB[0-9]+|ttyACM[0-9]+|bus/usb/[0-9]{3}/[0-9]{3}|dri/renderD[0-9]+)',item['path']) or type(item.get('group')) is not int or item['group']<0: raise Error('Ungültige gespeicherte Gerätezuordnung.')
        value=[item['id'] for item in value]
    else:
        inventory=devices() if inventory is None else inventory
        validate(value,inventory)
    found={item['id']:item for item in inventory}
    service=definition['services'][app]
    physical=[found[item] for item in value if found[item].get('driver')!='nvidia'];gpus=[item.removeprefix('nvidia:') for item in value if found[item].get('driver')=='nvidia']
    if physical: service['devices']=[item['path']+':'+item['path']+':rw' for item in physical]
    if gpus: service['deploy']={'resources':{'reservations':{'devices':[{'driver':'nvidia','device_ids':gpus,'capabilities':['gpu']}]}}}
    service['group_add']=[str(group) for group in sorted({item['group'] for item in physical})]
    return definition


class AppDevicesMixin:
    def app_devices_ready(self, record):
        configured=record.get("hardware") or []
        if not configured: return
        current={item["id"]:item for item in devices()}
        for item in configured:
            if item["id"] not in current or current[item["id"]].get("path")!=item.get("path"): raise Error("App-Gerät fehlt oder wurde neu zugeordnet. Geräteauswahl erneut prüfen.",409)

    def op_app_devices(self):
        return {'devices':devices(),'notes':['USB-Zuordnung gilt für das ausgewählte Gerät. Nach erneutem Anstecken ggf. neu auswählen.', 'GPU-Beschleunigung benötigt einen aktiven Host-Treiber und eine kompatible App. NVIDIA-GPUs werden angeboten, wenn NVIDIA-Treiber und Container Toolkit mit Docker-Runtime verfügbar sind.']}
