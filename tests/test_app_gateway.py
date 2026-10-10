import copy
import unittest
from titan.app_gateway import wrap, configuration, IMAGE
from titan.core import Error


class AppGatewayTests(unittest.TestCase):
    def setUp(self):
        self.definition = {'services': {'notes': {'image': 'example:1', 'container_name': 'titan-notes',
            'networks': {'default': {'aliases': ['web']}}, 'ports': ['18080:8080/tcp'],
            'volumes': [{'type': 'bind', 'source': '/private', 'target': '/data'}]},
            'notes-db': {'image': 'database:1', 'ports': [], 'volumes': [], 'depends_on': ['notes']}}}
        self.recipe = {'app_gateway': True, 'port': 8080}

    def test_only_gateway_is_published_data_and_aliases_stay_with_backend(self):
        before = copy.deepcopy(self.definition)
        result = wrap(self.definition, 'notes', self.recipe)['services']
        self.assertEqual(self.definition, before)
        self.assertEqual(result['notes']['ports'], ['18080:8080/tcp'])
        self.assertEqual(result['notes']['image'], IMAGE)
        self.assertEqual(result['notes-backend']['ports'], [])
        self.assertEqual(result['notes-backend']['volumes'], before['services']['notes']['volumes'])
        self.assertEqual(result['notes-backend']['networks']['default']['aliases'], ['web'])
        self.assertEqual(result['notes-db']['depends_on'], ['notes-backend'])
        self.assertFalse(result['notes']['volumes'])
        self.assertTrue(result['notes']['read_only'])

    def test_authentication_cannot_be_bypassed_with_extra_public_ports(self):
        for service in ('notes', 'notes-db'):
            definition = copy.deepcopy(self.definition)
            definition['services'][service]['ports'].append('9090:9090/tcp')
            with self.assertRaises(Error): wrap(definition, 'notes', self.recipe)

    def test_host_network_and_name_collision_are_refused(self):
        self.definition['services']['notes']['network_mode'] = 'host'
        with self.assertRaises(Error): wrap(self.definition, 'notes', self.recipe)
        del self.definition['services']['notes']['network_mode']
        self.definition['services']['notes-backend'] = {}
        with self.assertRaises(Error): wrap(self.definition, 'notes', self.recipe)

    def test_target_and_app_cannot_inject_configuration(self):
        for app, target, port in [('notes\n}', 'backend', 80), ('notes', 'backend; shell', 80), ('notes', 'backend', True)]:
            with self.assertRaises(Error): configuration(app, target, port)

    def test_no_gateway_recipe_keeps_existing_definition(self):
        self.assertIs(wrap(self.definition, 'notes', {'port': 8080}), self.definition)
