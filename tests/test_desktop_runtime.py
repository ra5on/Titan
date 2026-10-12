import unittest
from unittest.mock import Mock, patch

from titan.core import Error
from titan.desktop_runtime import DesktopRuntimeMixin


class Runtime(DesktopRuntimeMixin):
    pass


class DesktopRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.host = Runtime()
        self.host.desktop_status = lambda: {'running':True}
        self.host.vm_id = Mock(return_value='titan-guest')
        self.args = dict(id='a'*64, kind='vm', target='managed-guest', width=1000, height=700)

    def test_vm_endpoint_comes_from_managed_domain_only(self):
        with patch('titan.host.run', return_value='<domain><devices><graphics type="vnc" listen="127.0.0.1" port="5912" passwd="private"/></devices></domain>') as command:
            endpoint = self.host.op_desktop_open(**self.args)
        self.host.vm_id.assert_called_once_with('managed-guest')
        command.assert_called_once_with(['virsh','dumpxml','titan-guest'])
        self.assertEqual(endpoint, {'protocol':'vnc','hostname':'127.0.0.1','port':5912,'password':'private'})

    def test_vm_rejects_foreign_and_nonlocal_or_inactive_vnc(self):
        self.host.vm_id.side_effect = Error('Not managed',403)
        with patch('titan.host.run') as command, self.assertRaises(Error):
            self.host.op_desktop_open(**self.args)
        command.assert_not_called()
        self.host.vm_id.side_effect = None
        for graphics in ('<graphics type="vnc" listen="0.0.0.0" port="5912"/>',
                         '<graphics type="vnc" listen="127.0.0.1" port="-1"/>',
                         '<graphics type="spice" port="5912"/>'):
            with self.subTest(graphics=graphics), patch('titan.host.run', return_value='<domain><devices>'+graphics+'</devices></domain>'), self.assertRaises(Error):
                self.host.op_desktop_open(**self.args)

    def test_stopped_plugin_rejects_new_connections(self):
        self.host.desktop_status = lambda: {'running':False}
        with self.assertRaises(Error):
            self.host.op_desktop_open(**self.args)
        self.host.vm_id.assert_not_called()

    def test_container_name_collision_is_never_adopted(self):
        self.host._desktop_command = Mock(return_value='[{"Config":{"Labels":{}}}]')
        with self.assertRaises(Error):
            self.host._desktop_container('titan-guacd')

    def test_invalid_file_actions_do_not_reach_docker(self):
        self.host._desktop_container = Mock()
        for transfer in ({'action':'shell','command':'id'}, {'action':'read','name':'file','offset':0,'path':'/etc'}, {'action':[]}):
            with self.subTest(transfer=transfer), self.assertRaises(Error):
                self.host.op_desktop_files('a'*64, transfer)
        self.host._desktop_container.assert_not_called()

    def test_agent_limits_survive_web_registry_loss(self):
        names = ['titan-browser-' + f'{index:064x}' for index in range(8)]
        self.host._desktop_command = Mock(return_value='\n'.join(names + ['titan-guacd', 'unrelated']))
        self.host._desktop_container = Mock(return_value={'State':{'Running':True}})
        self.host.op_desktop_close = Mock()
        with self.assertRaises(Error) as error:
            self.host._desktop_browser_capacity()
        self.assertEqual(error.exception.status, 429)
        self.host._desktop_container.side_effect = lambda name: {'State':{'Running':name != names[0]}}
        self.host._desktop_browser_capacity()
        self.host.op_desktop_close.assert_called_once_with('0'*64)


if __name__ == '__main__':
    unittest.main()
