import unittest
from titan.launcher_layout import validate,load,save
from titan.core import Error
class Store:
    def __init__(self):self.data={}
    def config(self,key,default):return self.data.get(key,default)
    def set_config(self,key,value):self.data[key]=value
class Tests(unittest.TestCase):
    def test_folders_and_positions_survive_per_user_without_cross_account_access(self):
        store=Store();value={'items':['tool:vms',{'id':'folder-media','name':'Medien','items':['app:jellyfin','tool:files']}]}
        save(store,'alice',value);self.assertEqual(load(store,'alice'),value);self.assertEqual(load(store,'bob'),{'items':[]})
    def test_duplicate_nested_oversize_and_invalid_ids_are_rejected(self):
        for value in [{'items':['tool:vms','tool:vms']},{'items':[{'id':'folder-x','name':'X','items':[{'id':'folder-y'}]}]},{'items':['javascript:bad']},{'items':['tool:x'+str(i) for i in range(129)]},{'items':[{'id':'folder-x','name':'\n','items':[]}]}]:
            with self.subTest(value=value),self.assertRaises(Error):validate(value)
