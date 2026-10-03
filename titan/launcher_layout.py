"""Per-account launcher positions and one-level folders."""
import re
from .core import Error

def validate(value):
    if not isinstance(value,dict) or set(value)!={'items'} or not isinstance(value['items'],list) or len(value['items'])>128: raise Error('Ungültige Hauptmenü-Anordnung.')
    seen=set(); folders=set(); count=0
    def item(key):
        nonlocal count
        if not isinstance(key,str) or not re.fullmatch(r'(tool|app):[a-zA-Z0-9_-]{1,64}',key) or key in seen: raise Error('Ungültige oder doppelte Menü-App.')
        seen.add(key); count+=1
        if count>128: raise Error('Zu viele Menü-Apps.')
    for row in value['items']:
        if isinstance(row,str): item(row);continue
        if not isinstance(row,dict) or set(row)!={'id','name','items'} or not isinstance(row['id'],str) or not re.fullmatch(r'folder-[a-z0-9-]{1,40}',row['id']) or row['id'] in folders: raise Error('Ungültiger Menü-Ordner.')
        folders.add(row['id'])
        if not isinstance(row['name'],str) or not 1<=len(row['name'].strip())<=40 or any(ord(c)<32 for c in row['name']): raise Error('Ordnernamen mit 1 bis 40 Zeichen angeben.')
        if not isinstance(row['items'],list) or len(row['items'])>128: raise Error('Ungültiger Ordnerinhalt.')
        for key in row['items']: item(key)
    return value

def load(store,user):
    try:return validate(store.config('launcher-layout:'+user,{'items':[]}))
    except (Error,ValueError,TypeError):return {'items':[]}

def save(store,user,value):
    result=validate(value);store.set_config('launcher-layout:'+user,result);return result
