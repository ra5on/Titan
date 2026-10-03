import unittest
from titan.app_devices import apply,validate,device_label
from titan.core import Error
class TitanDevicesTests(unittest.TestCase):
    def test_real_usb_label_and_npu_mapping_do_not_require_privileged_access(self):
        label=device_label('/dev/bus/usb/001/004','usb',{'ID_VENDOR':'Samsung','ID_MODEL':'Portable_SSD','ID_SERIAL_SHORT':'serial-123'})
        self.assertIn('Samsung Portable SSD',label);self.assertIn('serial-123',label)
        device={'id':'/dev/accel/accel0','path':'/dev/accel/accel0','label':'Intel NPU','kind':'npu','group':109}
        definition=apply({'services':{'app':{}}},'app',[device])
        self.assertEqual(definition['services']['app']['devices'],['/dev/accel/accel0:/dev/accel/accel0:rw'])
        self.assertEqual(definition['services']['app']['group_add'],['109'])
        self.assertNotIn('privileged',definition['services']['app'])
        with self.assertRaises(Error):validate(['/dev/accel/accel0'],[])
        with self.assertRaises(Error):apply({'services':{'app':{}}},'app',[{**device,'path':'/etc/shadow'}])
