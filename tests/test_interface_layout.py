import unittest
from titan.core import Error
from titan.interface_layout import DEFAULT, load, save, validate

VM = '9417380c-6940-4b7c-9307-cf94e52780ec'


class Store:
    def __init__(self, value=None):
        self.values = {} if value is None else {'interface-layout:anna': value}

    def config(self, key, default):
        return self.values.get(key, default)

    def set_config(self, key, value):
        self.values[key] = value


class InterfaceLayoutTests(unittest.TestCase):
    def test_defaults_apply_and_partial_settings_are_completed(self):
        self.assertEqual(load(Store(), 'anna'), DEFAULT)
        saved = save(Store(), 'anna', {'transparency': 0, 'dock': ['tool:settings', 'app:titan-immich', 'vm:' + VM]})
        self.assertEqual(saved['transparency'], 0)
        self.assertEqual(saved['dock'], ['tool:settings', 'app:titan-immich', 'vm:' + VM])
        self.assertEqual(saved['widgets'], DEFAULT['widgets'])

    def test_layout_is_stored_per_account(self):
        store = Store()
        save(store, 'anna', {'dock_size': 'large'})
        self.assertEqual(load(store, 'anna')['dock_size'], 'large')
        self.assertEqual(load(store, 'ben')['dock_size'], 'medium')

    def test_settings_must_stay_in_the_dock(self):
        with self.assertRaises(Error):
            validate({'dock': ['tool:home', 'tool:files']})

    def test_malformed_values_are_rejected(self):
        for value in ({'transparency': 101}, {'transparency': '40'}, {'transparency': True}, {'dock_size': 'huge'},
                      {'dock': ['tool:settings', 'tool:settings']}, {'dock': ['tool:settings', 'app:../etc']},
                      {'dock': ['tool:settings', 'vm:not-a-uuid']}, {'widgets': ['cpu', 'gpu']}, {'widgets': ['cpu', 'cpu']},
                      {'hidden_apps': ['a b']}, {'pinned_vms': ['x']}, {'unknown': 1}, [], None):
            with self.subTest(value=value):
                with self.assertRaises(Error):
                    validate(value)

    def test_corrupt_stored_layout_falls_back_to_defaults(self):
        self.assertEqual(load(Store({'dock': 'broken'}), 'anna'), DEFAULT)


if __name__ == '__main__':
    unittest.main()
