"""Explicit character-device passthrough for apps, never privileged containers."""
import re
import stat
import json
import shutil
import subprocess
from os import major as os_major, minor as os_minor
from pathlib import Path
from .core import Error


def device_properties(path):
    """Read local udev names, never execute a value obtained from a device."""
    try:
        result=subprocess.run(['udevadm','info','--query=property','--name',str(path)],capture_output=True,text=True,timeout=2,check=True)
        return dict(line.split('=',1) for line in result.stdout[:16384].splitlines() if '=' in line)
    except (OSError,subprocess.SubprocessError): return {}


def device_label(path, kind, properties):
    vendor=properties.get('ID_VENDOR_FROM_DATABASE') or properties.get('ID_VENDOR','')
    model=properties.get('ID_MODEL_FROM_DATABASE') or properties.get('ID_MODEL','')
    serial=properties.get('ID_SERIAL_SHORT','')
    description=' '.join(value.replace('_',' ') for value in (vendor,model) if value)
    return f"{description or ('NPU' if kind=='npu' else 'Grafikbeschleuniger' if kind=='gpu' else 'USB-Gerät')}"+(f" · {serial}" if serial else '')+f" · {path}"


def devices(root='/dev'):
    base=Path(root); result=[]; seen=set()
    for pattern,kind in [('serial/by-id/*','usb'),('ttyUSB*','usb'),('ttyACM*','usb'),('bus/usb/*/*','usb'),('dri/renderD*','gpu'),('accel/accel*','npu'),('kfd','gpu')]:
        for path in sorted(base.glob(pattern)):
            try:
                real=path.resolve(strict=True); metadata=real.stat()
                if not real.is_relative_to(base.resolve()) or not stat.S_ISCHR(metadata.st_mode) or metadata.st_rdev in seen: continue
                seen.add(metadata.st_rdev)
                props=device_properties(real) if root=='/dev' else {}
                label=device_label(real,kind,props)
                if kind in ('gpu','npu') and root=='/dev':
                    sysdev=Path('/sys/dev/char')/f'{os_major(metadata.st_rdev)}:{os_minor(metadata.st_rdev)}'/'device'
                    try:
                        vendor=(sysdev/'vendor').read_text().strip()
                        brand={'0x8086':'Intel iGPU / GPU' if kind=='gpu' else 'Intel NPU','0x1002':'AMD GPU' if kind=='gpu' else 'AMD NPU','0x1022':'AMD NPU','0x10de':'NVIDIA GPU'}.get(vendor,'NPU' if kind=='npu' else 'GPU')
                        pci=sysdev.resolve().name
                        model=subprocess.run(['lspci','-s',pci],capture_output=True,text=True,timeout=2,check=True).stdout.strip().split(': ',1)[-1]
                        label=f'{brand} · {model or pci} · {real}'
                    except (OSError,subprocess.SubprocessError): pass
                if path.name=='kfd': label='AMD ROCm · Compute-Zugang · /dev/kfd'
                result.append({'id':str(path), 'path':str(real),'label':label[:512],'kind':kind,'group':metadata.st_gid})
            except OSError: continue
    if root=='/dev' and shutil.which('nvidia-smi') and shutil.which('nvidia-container-runtime'):
        try:
            info=subprocess.run(['docker','info','--format','{{json .Runtimes}}'],capture_output=True,text=True,timeout=5,check=True)
            if 'nvidia' in json.loads(info.stdout):
                query=subprocess.run(['nvidia-smi','--query-gpu=uuid,name','--format=csv,noheader'],capture_output=True,text=True,timeout=5,check=True)
                for row in query.stdout.splitlines()[:16]:
                    identifier,_,label=row.partition(',')
                    if re.fullmatch(r'GPU-[a-fA-F0-9-]{36}',identifier.strip()): result.append({'id':'nvidia:'+identifier.strip(),'path':None,'label':'NVIDIA GPU · '+label.strip(),'kind':'gpu','group':None,'driver':'nvidia'})
        except (OSError,ValueError,subprocess.SubprocessError): pass
    return result[:64]


def validate(value, inventory=None):
    if value is None: return []
    if not isinstance(value,list) or len(value)>16 or any(not isinstance(item,str) for item in value) or len(set(value))!=len(value): raise Error('Maximal 16 unterschiedliche App-Geräte auswählen.')
    found={item['id']:item for item in devices() if item['kind'] in ('usb','gpu','npu')} if inventory is None else {item['id']:item for item in inventory}
    if any(item not in found for item in value): raise Error('Ausgewähltes USB/GPU-Gerät ist nicht mehr verfügbar.',409)
    return value


def apply(definition, app, value, inventory=None):
    if not value: return definition
    if all(isinstance(item,dict) for item in value):
        inventory=value
        for item in value:
            if set(item)-{'id','path','label','kind','group','driver'} or item.get('kind') not in ('usb','gpu','npu') or not isinstance(item.get('id'),str): raise Error('Ungültige gespeicherte App-Geräte.')
            if item.get('driver')=='nvidia':
                if not re.fullmatch(r'nvidia:GPU-[a-fA-F0-9-]{36}',item['id']): raise Error('Ungültige GPU-ID.')
            elif not isinstance(item.get('path'),str) or not re.fullmatch(r'/dev/(?:ttyUSB[0-9]+|ttyACM[0-9]+|bus/usb/[0-9]{3}/[0-9]{3}|dri/renderD[0-9]+|accel/accel[0-9]+|kfd)',item['path']) or type(item.get('group')) is not int or item['group']<0: raise Error('Ungültige gespeicherte Gerätezuordnung.')
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
        return {'devices':devices(),'notes':['Nur tatsächlich erkannte Geräte mit aktivem Treiber werden angeboten. USB-Geräte werden mit Hersteller, Modell und Seriennummer angezeigt, soweit der Host diese meldet.', 'Intel-Grafik und NPU können gemeinsam ausgewählt werden. AMD-Compute benötigt je nach App zusätzlich den ROCm-Zugang. NVIDIA benötigt Container Toolkit; jede App muss die gewählte Beschleunigung unterstützen.']}
