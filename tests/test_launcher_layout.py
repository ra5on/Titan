import unittest
from titan.launcher_layout import validate,load,save
from titan.core import Error
class Store:
    def __init__(self):self.data={}
    def config(self,key,default):return self.data.get(key,default)
    def set_config(self,key,value):self.data[key]=value
class Tests(unittest.TestCase):
    def test_vm_shortcuts_require_canonical_uuid(self):
        key = "vm:12345678-1234-1234-1234-123456789abc"
        self.assertEqual(validate({"items": [key]})["items"], [key])
        for key in ("vm:../guest", "vm:not-a-uuid", "vm:javascript:alert(1)", "vm:12345678-1234-1234-1234-123456789ABC"):
            with self.subTest(key=key), self.assertRaises(Error):
                validate({"items": [key]})

    def test_folders_and_positions_survive_per_user_without_cross_account_access(self):
        store=Store();value={'items':['tool:vms',{'id':'folder-media','name':'Medien','items':['app:jellyfin','tool:files']}]}
        save(store,'alice',value);self.assertEqual(load(store,'alice'),value);self.assertEqual(load(store,'bob'),{'items':[]})
    def test_duplicate_nested_oversize_and_invalid_ids_are_rejected(self):
        for value in [{'items':['tool:vms','tool:vms']},{'items':[{'id':'folder-x','name':'X','items':[{'id':'folder-y'}]}]},{'items':['javascript:bad']},{'items':['tool:x'+str(i) for i in range(129)]},{'items':[{'id':'folder-x','name':'\n','items':[]}]}]:
            with self.subTest(value=value),self.assertRaises(Error):validate(value)
    def test_desktop_v2_roundtrip_and_empty_selection(self):
        value={'version':2,'items':['tool:files'],'positions':{'tool:files':{'x':4,'y':1}},'widgets':{'visible':False,'collapsed':True,'items':['ram','activity']}}
        store=Store();save(store,'alice',value);self.assertEqual(load(store,'alice'),value)
        save(store,'alice',{'version':2,'items':[]});self.assertEqual(load(store,'alice')['items'],[])
    def test_desktop_v2_rejects_invalid_coordinates_and_widgets(self):
        for extra in [{'version':True},{'version':3},{'positions':{'tool:files':{'x':-1,'y':0}}},{'positions':{'tool:files':{'x':True,'y':0}}},{'positions':{'tool:unknown':{'x':0,'y':0}}},{'widgets':{'items':['ram','ram']}},{'widgets':{'items':['root']}},{'widgets':{'visible':'false'}}]:
            with self.subTest(extra=extra),self.assertRaises(Error):validate({'items':['tool:files'],**extra})

    def test_desktop_preferences_are_validated_and_isolated_per_account(self):
        store=Store()
        for transparency in (0,40,100):
            value={'items':['tool:files'],'desktop':{'background_click':'minimize','transparency':transparency}}
            save(store,'alice',value)
            self.assertEqual(load(store,'alice'),value)
            self.assertEqual(load(store,'bob'),{'items':[]})
        for desktop in ([],None,{'extra':1},{'transparency':True},{'transparency':1.5},{'transparency':'40'},{'transparency':-1},{'transparency':101},{'background_click':'anything'},{'background_click':False}):
            with self.subTest(desktop=desktop),self.assertRaises(Error):
                validate({'items':[],'desktop':desktop})

    def test_color_modes_and_widget_positions_are_per_account(self):
        store=Store()
        for mode in ('light','dark','system'):
            for position in ({'x':0,'y':0},{'x':1000,'y':1000},{'x':432,'y':951}):
                value={'items':[],'desktop':{'color_mode':mode},'widgets':{'position':position}}
                save(store,'alice',value)
                self.assertEqual(load(store,'alice'),value)
                self.assertEqual(load(store,'bob'),{'items':[]})
        for extra in ({'desktop':{'color_mode':True}},{'desktop':{'color_mode':'unknown'}},{'widgets':{'position':None}},{'widgets':{'position':{'x':True,'y':0}}},{'widgets':{'position':{'x':1001,'y':0}}},{'widgets':{'position':{'x':1.5,'y':0}}},{'widgets':{'position':{'x':0}}},{'widgets':{'position':{'x':0,'y':0,'z':0}}}):
            with self.subTest(extra=extra),self.assertRaises(Error):validate({'items':[],**extra})

    def test_individual_widgets_retain_positions_and_reject_unselected_or_invalid_positions(self):
        store=Store()
        value={'items':[],'widgets':{'items':['clock','cpu'],'positions':{'clock':{'x':0,'y':1000},'cpu':{'x':541,'y':72}}}}
        save(store,'alice',value)
        self.assertEqual(load(store,'alice'),value)
        self.assertEqual(load(store,'bob'),{'items':[]})
        for positions in (None,[],{'ram':{'x':0,'y':0}},{'clock':{'x':True,'y':0}},{'clock':{'x':0,'y':-1}},{'clock':{'x':0.5,'y':0}},{'clock':{'x':0,'y':1001}},{'clock':{'x':0}},{'clock':{'x':0,'y':0,'z':1}}):
            with self.subTest(positions=positions),self.assertRaises(Error):
                validate({'items':[],'widgets':{'items':['clock'],'positions':positions}})
