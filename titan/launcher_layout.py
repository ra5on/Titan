"""Per-account launcher positions and one-level folders."""
import re
from .core import Error

KEY = r"(?:(?:tool|app):[a-zA-Z0-9_-]{1,64}|vm:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})"

def validate(value):
    if not isinstance(value,dict) or 'items' not in value or set(value)-{'items','hidden','version','positions','widgets','docker_added','icon_size','desktop'} or not isinstance(value['items'],list) or len(value['items'])>128: raise Error('Ungültige Hauptmenü-Anordnung.')
    if 'docker_added' in value and type(value['docker_added']) is not bool: raise Error('Ungültige Desktop-Initialisierung.')
    if 'icon_size' in value and value['icon_size'] not in ('small','medium','large'): raise Error('Ungültige Symbolgröße.')
    desktop=value.get('desktop',{})
    if not isinstance(desktop,dict) or set(desktop)-{'background_click','transparency','color_mode'}: raise Error('Ungültige Desktop-Einstellungen.')
    if 'color_mode' in desktop and desktop['color_mode'] not in ('light','dark','system'): raise Error('Ungültiger Darstellungsmodus.')
    if 'background_click' in desktop and desktop['background_click'] not in ('none','minimize'): raise Error('Ungültiges Desktop-Klickverhalten.')
    if 'transparency' in desktop and (type(desktop['transparency']) is not int or not 0<=desktop['transparency']<=100): raise Error('Transparenz muss zwischen 0 und 100 liegen.')
    seen=set(); folders=set(); count=0
    def item(key):
        nonlocal count
        if not isinstance(key,str) or not re.fullmatch(KEY,key) or key in seen: raise Error('Ungültige oder doppelte Menü-App.')
        seen.add(key); count+=1
        if count>128: raise Error('Zu viele Menü-Apps.')
    for row in value['items']:
        if isinstance(row,str): item(row);continue
        if not isinstance(row,dict) or set(row)!={'id','name','items'} or not isinstance(row['id'],str) or not re.fullmatch(r'folder-[a-z0-9-]{1,40}',row['id']) or row['id'] in folders: raise Error('Ungültiger Menü-Ordner.')
        folders.add(row['id'])
        if not isinstance(row['name'],str) or not 1<=len(row['name'].strip())<=40 or any(ord(c)<32 for c in row['name']): raise Error('Ordnernamen mit 1 bis 40 Zeichen angeben.')
        if not isinstance(row['items'],list) or len(row['items'])>128: raise Error('Ungültiger Ordnerinhalt.')
        for key in row['items']: item(key)
    if "hidden" in value:
        hidden=value["hidden"]
        if not isinstance(hidden,list) or len(hidden)>128 or any(not isinstance(key,str) or not re.fullmatch(KEY,key) for key in hidden) or len(set(hidden))!=len(hidden): raise Error("Ungültige ausgeblendete Menü-Apps.")
    if 'version' in value and (type(value['version']) is not int or value['version'] != 2): raise Error('Ungültige Desktop-Version.')
    roots={row if isinstance(row,str) else row['id'] for row in value['items']}
    positions=value.get('positions',{})
    if not isinstance(positions,dict) or len(positions)>128: raise Error('Ungültige Desktop-Positionen.')
    for key,pos in positions.items():
        if key not in roots or not isinstance(pos,dict) or set(pos)!={'x','y'} or any(type(pos[k]) is not int or not 0<=pos[k]<limit for k,limit in [('x',32),('y',128)]): raise Error('Ungültige Desktop-Position.')
    widgets=value.get('widgets',{})
    if not isinstance(widgets,dict) or set(widgets)-{'visible','collapsed','items','position','positions'}: raise Error('Ungültige Widgets.')
    if any(type(widgets[k]) is not bool for k in ('visible','collapsed') if k in widgets): raise Error('Ungültiger Widget-Status.')
    position=widgets.get('position')
    if 'position' in widgets and (not isinstance(position,dict) or set(position)!={'x','y'} or any(type(position[k]) is not int or not 0<=position[k]<=1000 for k in ('x','y'))): raise Error('Ungültige Widget-Position.')
    choices=widgets.get('items',[])
    allowed_widgets={'cpu','ram','health','notifications','activity','clock'}
    if not isinstance(choices,list) or len(choices)>6 or any(not isinstance(k,str) or k not in allowed_widgets for k in choices) or len(set(choices))!=len(choices): raise Error('Ungültige Widget-Auswahl.')
    widget_positions=widgets.get('positions',{})
    if not isinstance(widget_positions,dict) or len(widget_positions)>6: raise Error('Ungültige Widget-Positionen.')
    for key,point in widget_positions.items():
        if key not in choices or not isinstance(point,dict) or set(point)!={'x','y'} or any(type(point[k]) is not int or not 0<=point[k]<=1000 for k in ('x','y')): raise Error('Ungültige Widget-Position.')
    return value

def load(store,user):
    try:return validate(store.config('launcher-layout:'+user,{'items':[]}))
    except (Error,ValueError,TypeError):return {'items':[]}

def save(store,user,value):
    result=validate(value);store.set_config('launcher-layout:'+user,result);return result
