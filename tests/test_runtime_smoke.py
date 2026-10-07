import contextlib
import copy
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import struct
import shlex
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch
from titan import catalog as app_catalog
from titan.files import _text_content


spec = importlib.util.spec_from_file_location("titan_runtime_smoke", Path(__file__).resolve().parents[1] / "scripts/smoke-runtime.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class FakeGuest:
    def __init__(self, kvm=False):
        self.csrf = ""
        self.sessions = 0
        self.state = None
        self.vm = None
        self.vms = {}
        self.vm_settings = {}
        self.vm_instances = 0
        self.kvm = kvm
        self.password = None
        self.actions = []
        self.probes = []
        self.networks = {}
        self.app_network = None
        self.username = None
        self.users = {}
        self.shares = {}
        self.disk_size = 32 * 1024**3
        self.partition_size = 30 * 1024**3 - 1024**2
        self.filesystem_size = self.partition_size - 4096
        self.disk_revision = "a" * 64
        self.system_files = {}
        self.disk_grow_probes = 0

    def container(self):
        name = self.app_network.get("name") if self.app_network else "default"
        return {"networks": [{"name": name, "driver": "bridge", "ipv4": "172.30.241.10",
                              "ipv6": "", "gateway": "172.30.241.1", "internal": False}],
                "endpoints": [{"url": "http://10.0.2.15:18080/", "address": "10.0.2.15", "port": 18080,
                               "scope": "lan", "source": "published"}], "public_ip": None}

    def request(self, path, body=None, expected_status=None):
        if path == "/api/session":
            self.sessions += 1
            return {"setup_required": self.sessions == 1, "setup_csrf": "fixture-csrf", "demo": False,
                    "user": None if self.sessions == 1 else {"role": "admin"}}
        if path == "/api/setup":
            self.password = body["password"]
            self.username = body["name"]
            self.users[self.username] = {"name": self.username, "system_user": self.username, "role": "admin", "enabled": True, "uid": 1000}
            return {"ok": True}
        if path == "/api/login":
            return {"ok": True, "csrf": "session-csrf"}
        if path == "/api/catalog":
            cache = {"time": app_catalog.time.time(), "images": {}, "error": None}
            with patch.object(app_catalog, "_cache", cache), patch.object(app_catalog.urllib.request, "urlopen") as fetch:
                value = copy.deepcopy(app_catalog.catalog(include_legacy=not smoke.NATIVE_APP_CONTRACT))
                if not smoke.NATIVE_APP_CONTRACT:
                    value['apps'] = [item for item in value['apps'] if item['id'] in app_catalog.PACKAGES]
                fetch.assert_not_called()
            return value
        if path == "/api/status":
            return {"memory_total": 1000, "memory_used": 400, "memory_available": 600, "memory_free":600,
                    "cpu_percent": 20, "demo": False, "telemetry_errors": {}, "temperatures": []}
        if path == "/api/components":
            return {"components": {"docker": {"installed": True, "available": True, "daemon": True, "compose": True},
                                   "vms": {"installed": True, "daemon": True, "kvm": self.kvm, "available": self.kvm}}}
        if path == "/api/apps":
            return {"available": True, "installed": [{"id": "heimdall", "state": self.state,
                "container": self.container()}] if self.state else []}
        if path.startswith("/api/app-details?"):
            return {"container": self.container()}
        if path == "/api/app-networks":
            return {"available": True, "networks": list(self.networks.values()), "public_ip": None,
                    "host_addresses": [{"address": "10.0.2.15", "family": 4, "interface": "eth0"}], "warnings": []}
        if path == "/api/updates/system":
            return {"platform": "debian-rauc", "update_kind": "image", "health_confirmed": True, "booted": {"slot":"A", "digest": "sha256:" + "a" * 64},
                "staged": None, "rollback": None, "rollback_available": False, "rollback_queued": False,
                "reboot_required": False, "automatic_reboot": False, "reboot_scheduled": False}
        if path == "/api/system-disk":
            pending = self.disk_size - 2 * 1024**3 - 1024**2 - self.partition_size
            return {"supported": True, "available": pending >= 1024**2 or self.partition_size - self.filesystem_size >= 1024**2, "filesystem": "xfs", "mountpoint": "/var",
                "disk": "/dev/fixture-disk", "partition": "/dev/fixture-partition", "partition_number": 4,
                "partition_start": 2 * 1024**3, "sector_size": 512, "disk_uuid": "fixture-disk-uuid",
                "partition_uuid": "fixture-partition-uuid", "filesystem_uuid": "fixture-filesystem-uuid",
                "disk_size": self.disk_size, "partition_size": self.partition_size, "filesystem_size": self.filesystem_size,
                "filesystem_used": 1024**3, "filesystem_available": self.filesystem_size - 1024**3,
                "partition_growable_bytes": pending, "filesystem_growable_bytes": self.partition_size - self.filesystem_size,
                "growable_bytes": pending + self.partition_size - self.filesystem_size, "revision": self.disk_revision}
        if path == "/api/actions":
            if expected_status != 400 or body["arguments"]["confirmation"] != "INVALID":
                raise AssertionError("Fixture must reject invalid update confirmation.")
            return {"error": "Confirmation rejected"}
        if path == "/api/users":
            return {"web": list(self.users.values()), "system": list(self.users.values()), "service_user": "titan-files"}
        if path == "/api/shares/access":
            return {"service_active": True, "port": 445}
        if path == "/api/shares":
            return list(self.shares.values())
        if path == "/api/files" and body["share"] == "@system":
            target = body["path"]
            if body["action"] == "create":
                assert target not in self.system_files
                self.system_files[target] = _text_content(body["data"])
            elif body["action"] == "read":
                return {"data": base64.b64encode(self.system_files[target]).decode(), "total": len(self.system_files[target])}
            elif body["action"] == "delete":
                assert body["confirmation_path"] == "/" + target
                del self.system_files[target]
            return {"ok": True}
        if path.startswith("/api/files?share="):
            return {"entries": [], "total": 0}
        if path == "/api/isos":
            return {"complete": True}
        if path == "/api/vm-options":
            return {"network_options":{"bridges":["virbr0"]}}
        if path == "/api/vms":
            return {"available": True, "vms": [{"id": identifier, "state": state, **self.vm_settings.get(identifier,{"firmware":"bios"})} for identifier, state in self.vms.items()]}
        if path.startswith("/api/vm-image-info?"):
            return {"path": "/var/lib/libvirt/images/titan/smoke-vm.qcow2", "format": "qcow2", "size": 197632,
                    "virtual_size": 8 * 1024**3, "min_disk_gb": 8, "source_retained": True, "revision": "a" * 64}
        raise AssertionError("Unexpected fixture route: " + path)

    def action(self, operation, arguments):
        self.actions.append((operation, arguments))
        if operation == "app_install":
            self.state = "running"
            self.app_network = arguments.get("network")
        elif operation == "app_action":
            self.state = {"stop": "exited", "start": "running", "remove": None}[arguments["action"]]
        elif operation == "vm_create":
            self.vm = "shut off"
            self.vm_instances += 1
            identifier = "fixture-clone" if arguments["name"] == "smoke-image-clone" else "fixture-vm" if self.vm_instances == 1 else "fixture-vm-new"
            self.vm_settings[identifier] = {"firmware":arguments.get("firmware","bios")}
            self.vms[identifier] = self.vm
            return {"id": identifier, "ok": True, "disk_path": "/var/lib/libvirt/images/titan/" + arguments["name"] + ("--"+"f"*32 if self.vm_instances>2 else "") + ".qcow2",
                    "source_retained": bool(arguments.get("disk_image"))}
        elif operation == "vm_update":
            self.vm_settings[arguments["vm"]].update({key:arguments[key] for key in ("firmware","network") if key in arguments})
        elif operation == "vm_action":
            self.vm = {"start": "running", "poweroff": "shut off"}[arguments["action"]]
            self.vms[arguments["vm"]] = self.vm
        elif operation == "vm_remove":
            self.vm = None
            self.vms.pop(arguments["vm"])
            return {"disk_retained": True}
        elif operation == "app_network_create":
            name = arguments["name"]
            self.networks[name] = {"id": hashlib.sha256(name.encode()).hexdigest(), "name": name,
                "driver": "bridge", "managed": True, "scope": "local", "removable": True,
                "selectable": True, "static_ipv4": True, "internal": False, "containers": [], "used_by": [],
                "subnets": [{"subnet": arguments.get("subnet", "172.30.0.0/24"),
                             "gateway": arguments.get("gateway", "172.30.0.1"), "family": 4}]}
            return {"ok": True, "network": copy.deepcopy(self.networks[name])}
        elif operation == "app_network_remove":
            del self.networks[arguments["name"]]
        elif operation == "share_create":
            self.shares[arguments["name"]] = dict(arguments)
        elif operation == "share_remove":
            del self.shares[arguments["name"]]
            return {"ok": True, "data_retained": True}
        elif operation == "system_disk_grow":
            changed = self.disk_revision == "b" * 64
            if changed:
                self.partition_size += 4 * 1024**3
                self.filesystem_size += 4 * 1024**3
                self.disk_revision = "c" * 64
            return {"ok": True, "changed": changed, "partition_grown": changed, "filesystem_grown": changed}
        return {"ok": True}

    def grow_disposable_system_disk(self):
        self.disk_grow_probes += 1
        self.disk_size = 36 * 1024**3
        self.disk_revision = "b" * 64
        return {"overlay_grown": True, "virtual_size_before": 32 * 1024**3, "virtual_size_after": 36 * 1024**3}

    def user_create(self, name, password):
        self.actions.append(("account_create", {"name": name}))
        self.users[name] = {"name": name, "system_user": name, "role": "user", "enabled": True, "uid": 1000 + len(self.users)}
        return {"ok": True}

    def user_remove(self, name):
        self.actions.append(("user_remove", {"name": name}))
        del self.users[name]
        return {"ok": True}

    def smb_access(self, writer, reader, outsider, share):
        self.assertions = {"writer": writer[0] == self.username and writer[1] == self.password,
                           "reader": reader[0] in self.users, "outsider": outsider[0] in self.users,
                           "share": share in self.shares}
        return {"writer_read_write": True, "downloaded_content_matches": True, "reader_read": True,
                "reader_write_denied": True, "unauthorized_connect_denied": True,
                "unauthorized_share_hidden": True, "test_file_removed": True}

    def app_http_ready(self):
        self.probes.append(("app_http", self.state))
        return {"http_status": 200, "app_page": True}

    def console_assets(self):
        self.probes.append(("console_assets", self.vm))
        return {"console_http": True, "novnc_assets": True}

    def console_rfb(self, identifier):
        self.probes.append(("console_rfb", self.vm))
        return {"authenticated_websocket": True, "rfb_protocol": "3.8", "display_width": 640, "display_height": 480}


class RuntimeSmokeTests(unittest.TestCase):
    def run_fixture(self, client):
        with patch.object(smoke.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            return smoke.RuntimeSmoke(client).run()

    def test_actual_lifecycle_sequence_and_hardware_skip_are_distinct(self):
        client = FakeGuest()
        report = self.run_fixture(client)
        self.assertTrue(report["ok"])
        vm = next(check for check in report["checks"] if check["name"] == "vm_domain_lifecycle")
        self.assertEqual(vm["status"], "skipped")
        self.assertIn("Nested KVM", vm["detail"])
        self.assertEqual([arguments["action"] for operation, arguments in client.actions if operation == "app_action"],
                         ["stop", "start", "stop", "remove"] * 2)
        self.assertNotIn(client.password, json.dumps(report))
        self.assertNotIn("session-csrf", json.dumps(report))
        self.assertEqual(client.probes, [("app_http", "running")] * 4)

    def test_debian_runtime_requires_login_protection_check(self):
        runner = smoke.RuntimeSmoke(Mock())
        runner.kvm = False
        for name in ('setup', 'catalog', 'login_protection', 'storage_data_boundary', 'custom_service_containment', 'storage_components', 'debian_updates', 'metrics', 'smb', 'components', 'docker', 'docker_network', 'docker_stack', 'docker_native'):
            setattr(runner, name, Mock(return_value={}))
        with contextlib.redirect_stdout(io.StringIO()): report = runner.run(debian_ab=True)
        runner.login_protection.assert_called_once_with()
        runner.storage_data_boundary.assert_called_once_with()
        runner.custom_service_containment.assert_called_once_with()
        runner.storage_components.assert_called_once_with()
        self.assertEqual(next(item for item in report['checks'] if item['name'] == 'login_protection')['status'], 'passed')

    def test_real_catalog_route_checks_all_guidance_without_publishing_credentials(self):
        client = FakeGuest()
        original = client.request
        client.request = Mock(side_effect=original)
        report = self.run_fixture(client)
        self.assertTrue(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "app_catalog_first_login")
        self.assertEqual(check["values"]["app_count"], 1)
        self.assertEqual(sum(check["values"]["first_login_mode_counts"].values()), 1)
        self.assertEqual(set(check["values"]), {"app_count", "first_login_mode_counts", "ok"})
        client.request.assert_any_call("/api/catalog")
        self.assertNotIn("admin123", json.dumps(report))

    def test_legacy_empty_catalog_before_bigbear_activation_is_valid(self):
        client = Mock()
        client.request.return_value = {'apps': [], 'source': 'Titan AppStore', 'error': None}
        with patch.object(smoke, 'NATIVE_APP_CONTRACT', False):
            result = smoke.RuntimeSmoke(client).catalog()
        self.assertEqual(result['app_count'], 0)
        self.assertTrue(result['ok'])

    def test_guest_auto_catalog_public_metadata_needs_no_runner_private_recipe(self):
        from titan.store_recipes import recipes
        document = {'schema':1, 'name':'BigBear', 'apps':[{'id':'smoke-catalog', 'name':'Smoke App',
            'description':'Catalog boundary fixture.', 'image':'example/app:1.0', 'port':8080,
            'documentation':smoke.LEGACY_STACK_URL + '/tree/main/Apps/smoke-catalog',
            'login_note':'Create an account in the app.',
            'stack':{'primary':'web','services':{'web':{'image':'example/app:1.0','environment':{},'mounts':[]}}},
            'stack_fields':[{'key':'stack_password','label':'PASSWORD', 'type':'password','default':'',
                'required':True,'min_length':1,'max_length':1000}]}]}
        _, parsed = recipes(document, smoke.LEGACY_STACK_URL)
        identifier, recipe = next(iter(parsed.items()))
        public = {key:value for key,value in recipe.items() if key not in ('environment','stack')}
        public.update(id=identifier, containers=1, version='latest', deprecated=False, architectures=[])
        self.assertNotIn(identifier, app_catalog.APPS)
        client = Mock()
        client.request.return_value = {'apps':[public], 'source':'Titan AppStore', 'error':None,
            'store_status':{'state':'ready','accepted':1}, 'skipped':[],'installed_recipes':[]}
        with patch.object(smoke, 'NATIVE_APP_CONTRACT', False):
            result = smoke.RuntimeSmoke(client).catalog()
        self.assertEqual(result['app_count'], 1)
        self.assertEqual(result['first_login_mode_counts']['documentation'], 1)
        for change in ({'environment':{'PASSWORD':'private-fixture-secret'}},
                       {'first_login':{**public['first_login'],'password':'private-fixture-secret'}},
                       {'install_schema':[{**public['install_schema'][0], 'default':'private-fixture-secret'}]},
                       {'store_url':'https://github.com/untrusted/source'}):
            client.request.return_value['apps'] = [{**public, **change}]
            with self.subTest(change=list(change)), patch.object(smoke, 'NATIVE_APP_CONTRACT', False), self.assertRaises(smoke.SmokeFailure):
                smoke.RuntimeSmoke(client).catalog()

    def stack_fixture(self, schema=None):
        url = smoke.LEGACY_STACK_URL
        store = "bigbear"
        app = smoke.LEGACY_STACK_ID
        state = {"installed": False, "store": False, "containers": ["running", "running"]}
        actions, requests = [], []
        client = SimpleNamespace(actions=actions, requests=requests, state=state, app=app, store=store)

        def request(path):
            requests.append((path, state["installed"]))
            if path == "/api/app-stores":
                return {"stores": [{"id": store, "url": url, "enabled": True}] if state["store"] else []}
            if path == "/api/catalog":
                return {"apps": ([{"id": identifier} for identifier in app_catalog.PACKAGES] +
                                 ([{"id": app, "containers": 2, "install_schema": schema or []}] if state["store"] else [])),
                        "installed_recipes": [{"id": app, "containers": 2}] if state["installed"] else []}
            if path == "/api/apps":
                return {"installed": [{"id": app, "state": "running"}] if state["installed"] else []}
            if path == "/api/app-metrics":
                return {"apps": {app: {"cpu_percent": 2.0, "memory_bytes": 3000000,
                                       "disk_read_bytes": 4000, "disk_write_bytes": 9000}}}
            if path == "/api/docker-engine":
                return {"containers": [{"id": "fixture-" + str(index), "managed_app": app,
                                         "project": "titan-fixture-project", "state": value}
                                        for index, value in enumerate(state["containers"])]}
            raise AssertionError("Unexpected stack fixture route: " + path)

        def action(operation, arguments, **parameters):
            actions.append((operation, arguments))
            if operation == "app_store_add":
                self.assertEqual(arguments, {"url": smoke.LEGACY_STACK_URL, "trusted": True})
                self.assertEqual(smoke.LEGACY_STACK_URL, "https://github.com/bigbeartechworld/big-bear-dockge")
                self.assertFalse(state["store"])
                state["store"] = True
                return {"ok": True, "apps": 1, "name": "Titan runtime fixture"}
            if operation == "app_install":
                self.assertEqual(parameters, {"timeout": 900})
                self.assertTrue(state["store"])
                self.assertEqual(arguments["app"], app)
                self.assertEqual(arguments["port"], 18080)
                expected = {field["key"] for field in schema or [] if field["type"] == "password" and not field.get("generated")}
                self.assertEqual(set(arguments["options"]), expected)
                for value in arguments["options"].values():
                    self.assertRegex(value, r"^Test-[a-f0-9]{48}$")
                state["installed"] = True
            elif operation == "docker_container_batch":
                self.assertEqual(arguments["containers"], ["fixture-0", "fixture-1"])
                state["containers"] = ["exited" if arguments["action"] == "stop" else "running"] * 2
            elif operation == "app_action":
                self.assertEqual(arguments, {"app": app, "action": "remove"})
                state["installed"] = False
            elif operation == "app_store_remove":
                self.assertFalse(state["installed"])
                self.assertEqual(arguments, {"store": store})
                state["store"] = False
            else:
                raise AssertionError("Unexpected stack fixture action: " + operation)
            return {"ok": True}

        def http_ready(**options):
            self.assertEqual(options, {"timeout": 240, "expected_app": "nextcloud"})
            self.assertTrue(state["installed"])
            self.assertEqual(state["containers"], ["running", "running"])
            return {"http_status": 200, "app_page": True}

        client.request, client.action = request, action
        client.app_http_ready = Mock(side_effect=http_ready)
        return client

    def test_imported_stack_lifecycle_uses_installed_recipe_with_curated_catalog(self):
        client = self.stack_fixture()
        result = smoke.RuntimeSmoke(client).legacy_docker_stack()
        self.assertEqual(result["containers"], 2)
        self.assertTrue(all(result[key] for key in ("import", "install", "http", "compose_grouping",
                                                   "batch_stop_start", "live_resources", "remove")))
        self.assertEqual(client.app_http_ready.call_count, 2)
        self.assertEqual([arguments["action"] for operation, arguments in client.actions
                          if operation == "docker_container_batch"], ["stop", "start"])
        self.assertEqual([installed for path, installed in client.requests if path == "/api/catalog"], [False, False, True])
        self.assertEqual(set(row["id"] for row in client.request("/api/catalog")["apps"]), set(app_catalog.PACKAGES))
        self.assertFalse(client.state["installed"])
        self.assertFalse(client.state["store"])

    def test_auto_bootstrapped_stack_is_reused_without_duplicate_add_or_source_removal(self):
        client = self.stack_fixture()
        client.state['store'] = True
        result = smoke.RuntimeSmoke(client).legacy_docker_stack()
        self.assertTrue(result['install'] and result['remove'])
        self.assertTrue(client.state['store'])
        self.assertFalse(client.state['installed'])
        self.assertFalse(any(operation.startswith('app_store_') for operation, _ in client.actions))

    def test_bootstrap_finishing_between_inventory_and_add_uses_real_published_offer(self):
        client = self.stack_fixture()
        action = client.action
        def raced(operation, arguments, **parameters):
            if operation == 'app_store_add':
                client.state['store'] = True
                raise smoke.SmokeFailure('Store already exists.')
            return action(operation, arguments, **parameters)
        client.action = raced
        self.assertTrue(smoke.RuntimeSmoke(client).legacy_docker_stack()['http'])
        self.assertTrue(client.state['store'])
        self.assertFalse(client.state['installed'])

    def test_missing_store_import_failure_is_not_misclassified_as_bootstrap_race(self):
        client = self.stack_fixture()
        action = client.action
        def failed(operation, arguments, **parameters):
            if operation == 'app_store_add': raise smoke.SmokeFailure('Store download failed.')
            return action(operation, arguments, **parameters)
        client.action = failed
        with self.assertRaisesRegex(smoke.SmokeFailure, 'download failed'):
            smoke.RuntimeSmoke(client).legacy_docker_stack()
        self.assertFalse(client.state['installed'])
        self.assertFalse(client.state['store'])

    def test_preexisting_stack_installation_is_never_removed_by_runtime_check(self):
        client = self.stack_fixture()
        client.state.update(store=True, installed=True)
        with self.assertRaisesRegex(smoke.SmokeFailure, 'pre-existing'):
            smoke.RuntimeSmoke(client).legacy_docker_stack()
        self.assertTrue(client.state['installed'])
        self.assertEqual(client.actions, [])

    def test_bigbear_stack_supplies_private_required_passwords_before_install(self):
        client = self.stack_fixture(schema=[
            {"key": "database", "type": "password", "required": True},
            {"key": "administrator", "type": "password", "required": True},
            {"key": "generated", "type": "password", "generated": True},
            {"key": "username", "type": "text", "default": "admin"}])
        result = smoke.RuntimeSmoke(client).legacy_docker_stack()
        self.assertTrue(result["import"] and result["remove"])
        install = next(args for op, args in client.actions if op == "app_install")
        self.assertNotEqual(install["options"]["database"], install["options"]["administrator"])
        self.assertNotIn(install["options"]["database"], json.dumps(result))
        self.assertFalse(client.state["store"])

    def test_imported_stack_rejects_bad_import_before_install_and_cleans_source(self):
        client = self.stack_fixture()
        original = client.action

        def action(operation, arguments, **parameters):
            result = original(operation, arguments, **parameters)
            return {**result, "apps": 0} if operation == "app_store_add" else result

        client.action = action
        with self.assertRaisesRegex(smoke.SmokeFailure, "source was not imported"):
            smoke.RuntimeSmoke(client).legacy_docker_stack()
        self.assertNotIn("app_install", [operation for operation, _ in client.actions])
        self.assertFalse(client.state["store"])

    def test_imported_stack_requires_real_inventory_metadata_metrics_and_grouping(self):
        failures = [
            ("/api/catalog", lambda value: value.update(installed_recipes=[]), "source was not translated"),
            ("/api/catalog", lambda value: value["installed_recipes"][0].update(containers=1) if value["installed_recipes"] else None, "source was not translated"),
            ("/api/apps", lambda value: value["installed"][0].update(state="exited") if value["installed"] else None,
             "managed running state"),
            ("/api/app-metrics", lambda value: value.update(apps={}), "statistics are unavailable"),
            ("/api/docker-engine", lambda value: value["containers"][0].update(project="other-project"), "grouping unavailable"),
            ("/api/docker-engine", lambda value: value["containers"][0].update(state="running"), "stop left a service running"),
        ]
        for route, mutation, error in failures:
            client = self.stack_fixture()
            original = client.request

            def request(path):
                value = original(path)
                if path == route:
                    mutation(value)
                return value

            client.request = request
            with self.subTest(route=route, error=error), self.assertRaisesRegex(smoke.SmokeFailure, error):
                smoke.RuntimeSmoke(client).legacy_docker_stack()
            self.assertFalse(client.state["installed"])
            self.assertFalse(client.state["store"])

    def test_imported_stack_http_failure_fails_and_removes_created_resources(self):
        client = self.stack_fixture()
        client.app_http_ready.side_effect = smoke.SmokeFailure("Stack HTTP endpoint did not respond.")
        with self.assertRaisesRegex(smoke.SmokeFailure, "HTTP endpoint"):
            smoke.RuntimeSmoke(client).legacy_docker_stack()
        self.assertFalse(client.state["installed"])
        self.assertFalse(client.state["store"])

    def native_stack_fixture(self):
        state={'installed':False,'running':True}
        actions=[];requests=[]
        client=SimpleNamespace(actions=actions,requests=requests,state=state)
        def request(path):
            requests.append(path)
            if path=='/api/apps':
                return {'installed':[{'id':smoke.RUNTIME_STACK_ID,'state':'running'}] if state['installed'] else []}
            if path=='/api/catalog':
                return {'apps':[{'id':'titan-cloudflared'}],'installed_recipes':[{'id':smoke.RUNTIME_STACK_ID,'containers':2}] if state['installed'] else []}
            if path=='/api/app-metrics':
                return {'apps':{smoke.RUNTIME_STACK_ID:{'cpu_percent':1,'memory_bytes':1024,'disk_read_bytes':0,'disk_write_bytes':0}}}
            if path=='/api/docker-engine':
                return {'containers':[{'id':'native-'+str(i),'managed_app':smoke.RUNTIME_STACK_ID,'project':'native-fixture','state':'running' if state['running'] else 'exited'} for i in range(2)]}
            raise AssertionError('Native fixture attempted a store or unexpected route: '+path)
        def action(operation,arguments,**parameters):
            actions.append((operation,arguments))
            if operation=='app_install':
                self.assertEqual(arguments,{'app':smoke.RUNTIME_STACK_ID,'port':18080,'options':{}})
                state['installed']=True
            elif operation=='docker_container_batch':state['running']=arguments['action']=='start'
            elif operation=='app_action':
                self.assertEqual(arguments,{'app':smoke.RUNTIME_STACK_ID,'action':'remove'})
                state['installed']=False
            else:raise AssertionError('Native fixture attempted a store mutation: '+operation)
            return {'ok':True}
        client.request=request;client.action=action;client.app_http_ready=Mock(return_value={'http_status':200})
        return client

    def test_native_stack_uses_private_fixture_without_publishing_or_importing_a_store(self):
        client=self.native_stack_fixture()
        with patch.object(smoke,'NATIVE_APP_CONTRACT',True):result=smoke.RuntimeSmoke(client).docker_stack()
        self.assertEqual(result['source'],'bundled-fixture')
        self.assertEqual(result['containers'],2)
        self.assertTrue(result['compose_grouping'] and result['live_resources'] and result['remove'])
        self.assertFalse(client.state['installed'])
        self.assertNotIn('/api/app-stores',client.requests)
        self.assertEqual(client.app_http_ready.call_args.kwargs,{'timeout':240,'expected_app':'runtime-stack'})

    def test_native_stack_never_replaces_a_preexisting_installation(self):
        client=self.native_stack_fixture();client.state['installed']=True
        with patch.object(smoke,'NATIVE_APP_CONTRACT',True),self.assertRaisesRegex(smoke.SmokeFailure,'pre-existing'):
            smoke.RuntimeSmoke(client).docker_stack()
        self.assertEqual(client.actions,[])
        self.assertTrue(client.state['installed'])

    def test_native_stack_http_failure_only_cleans_its_own_created_app(self):
        client=self.native_stack_fixture();client.app_http_ready.side_effect=smoke.SmokeFailure('fixture HTTP failed')
        with patch.object(smoke,'NATIVE_APP_CONTRACT',True),self.assertRaisesRegex(smoke.SmokeFailure,'HTTP failed'):
            smoke.RuntimeSmoke(client).docker_stack()
        self.assertFalse(client.state['installed'])
        self.assertEqual(client.actions[-1],('app_action',{'app':smoke.RUNTIME_STACK_ID,'action':'remove'}))

    def test_frozen_legacy_contract_reuses_the_legacy_stack_gate(self):
        runtime=smoke.RuntimeSmoke(Mock());runtime.legacy_docker_stack=Mock(return_value={'legacy':True})
        with patch.object(smoke,'NATIVE_APP_CONTRACT',False):self.assertEqual(runtime.docker_stack(),{'legacy':True})
        runtime.legacy_docker_stack.assert_called_once_with()

    def test_live_update_status_and_invalid_confirmations_do_not_stage_or_reboot(self):
        client = FakeGuest()
        original = client.request
        client.request = Mock(side_effect=original)
        report = self.run_fixture(client)
        self.assertTrue(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "system_update_state_confirmation")
        self.assertEqual(check["status"], "passed")
        self.assertFalse(check["values"]["automatic_reboot"])
        self.assertTrue(check["values"]["first_install_rollback_unavailable"])
        requests = [call for call in client.request.call_args_list if call.args[0] == "/api/actions"
                    and call.args[1]["operation"] in {"update_rollback", "system_reboot"}]
        self.assertEqual(len(requests), 2)
        self.assertEqual([call.args[1]["operation"] for call in requests], ["update_rollback", "system_reboot"])
        self.assertTrue(all(call.kwargs == {"expected_status": 400} for call in requests))
        self.assertFalse(any(operation in {"update_rollback", "system_reboot"} for operation, _ in client.actions))

    def test_system_disk_checks_real_capacity_identity_data_and_idempotence(self):
        client = FakeGuest()
        original = client.request
        self.assertFalse(original("/api/system-disk")["available"])
        client.request = Mock(side_effect=original)
        report = self.run_fixture(client)
        self.assertTrue(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "system_disk_growth")
        value = check["values"]
        self.assertTrue(value["first_boot_auto_growth"])
        self.assertTrue(value["partition_start_and_uuids_preserved"])
        self.assertTrue(value["sentinel_sha256_unchanged"])
        self.assertTrue(value["sentinel_removed"])
        self.assertEqual(value["partition_size_after"] - value["partition_size_before"], 4 * 1024**3)
        self.assertEqual(value["filesystem_size_after"] - value["filesystem_size_before"], 4 * 1024**3)
        self.assertEqual(client.disk_grow_probes, 1)
        self.assertEqual(client.system_files, {})
        self.assertFalse(original("/api/system-disk")["available"])
        creates = [call.args[1] for call in client.request.call_args_list if call.args[0] == "/api/files"
                   and call.args[1]["action"] == "create"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(_text_content(creates[0]["data"]), b"Titan disposable system-disk growth sentinel.\n")
        grows = [arguments for operation, arguments in client.actions if operation == "system_disk_grow"]
        self.assertEqual([arguments["expected_revision"] for arguments in grows], ["a" * 64, "b" * 64, "c" * 64])
        self.assertTrue(all(arguments["confirmation"] == "ERWEITERN" for arguments in grows))
        client.request.assert_any_call("/api/actions", {"operation": "system_disk_grow", "arguments": {
            "expected_revision": "a" * 64, "confirmation": "INVALID"}}, expected_status=400)
        self.assertNotIn("fixture-", json.dumps(value))

    def test_system_disk_unsupported_or_not_auto_grown_blocks_disk_mutation(self):
        for change in ({"supported": False}, {"available": True}, {"available": "private-value"}, {"filesystem": "ext4"},
                       {"disk_size": 22 * 1024**3}, {"growable_bytes": 4 * 1024**3},
                       {"filesystem_size": True}, {"revision": "private-revision"}):
            client = FakeGuest()
            original = client.request
            def request(path, body=None, expected_status=None):
                value = original(path, body, expected_status)
                if path == "/api/system-disk": value.update(change)
                return value
            client.request = request
            with self.subTest(change=change):
                report = self.run_fixture(client)
                self.assertFalse(report["ok"])
                self.assertEqual(client.disk_grow_probes, 0)
                self.assertFalse(any(operation == "system_disk_grow" for operation, _ in client.actions))
                self.assertEqual(client.system_files, {})
                self.assertNotIn("private-revision", json.dumps(report))

    def test_system_disk_metadata_identity_change_blocks_manual_grow_and_cleans_sentinel(self):
        for field in ("disk", "partition", "partition_number", "partition_start", "disk_uuid", "partition_uuid", "filesystem_uuid", "sector_size"):
            client = FakeGuest()
            original = client.request
            def request(path, body=None, expected_status=None):
                value = original(path, body, expected_status)
                if path == "/api/system-disk" and client.disk_grow_probes:
                    value[field] = 4096 if field == "sector_size" else 6 if field == "partition_number" else 2 * 1024**3 + 512 if field == "partition_start" else "private-identity"
                return value
            client.request = request
            with self.subTest(field=field):
                report = self.run_fixture(client)
                self.assertFalse(report["ok"])
                self.assertEqual(client.system_files, {})
                self.assertEqual(len([item for item in client.actions if item[0] == "system_disk_grow"]), 1)
                self.assertNotIn("private-identity", json.dumps(report))

    def test_system_disk_requires_partition_and_xfs_to_grow_and_cleans_sentinel(self):
        for skipped in ("partition_size", "filesystem_size", "changed", "partition_grown", "filesystem_grown"):
            client = FakeGuest()
            original = client.action
            def action(operation, arguments):
                before = getattr(client, skipped, None)
                pending = client.disk_revision == "b" * 64
                value = original(operation, arguments)
                if operation == "system_disk_grow" and pending:
                    if skipped in ("partition_size", "filesystem_size"): setattr(client, skipped, before)
                    else: value[skipped] = False
                return value
            client.action = action
            with self.subTest(skipped=skipped):
                report = self.run_fixture(client)
                self.assertFalse(report["ok"])
                self.assertEqual(client.system_files, {})

    def test_system_disk_requires_unchanged_sentinel_content(self):
        client = FakeGuest()
        original = client.grow_disposable_system_disk
        def grow():
            value = original()
            for key in client.system_files: client.system_files[key] = b"private-corrupt-content"
            return value
        client.grow_disposable_system_disk = grow
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        self.assertEqual(client.system_files, {})
        check = next(item for item in report["checks"] if item["name"] == "system_disk_growth")
        self.assertIn("SHA256", check["detail"])
        self.assertNotIn("private-corrupt-content", json.dumps(report))

    def test_system_disk_growth_failure_keeps_other_real_runtime_gates(self):
        client = FakeGuest(kvm=True)
        client.grow_disposable_system_disk = Mock(side_effect=smoke.SmokeFailure("Disposable QMP failed."))
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        statuses = {item["name"]: item["status"] for item in report["checks"]}
        self.assertEqual(statuses["system_disk_growth"], "failed")
        self.assertTrue(all(statuses[name] == "passed" for name in (
            "smb_multiuser_access", "docker_app_lifecycle", "docker_custom_network_lifecycle", "vm_domain_lifecycle")))
        self.assertEqual(client.system_files, {})

    def test_smb_uses_initial_admin_and_separate_readonly_and_unauthorized_accounts_then_cleans_up(self):
        client = FakeGuest()
        report = self.run_fixture(client)
        self.assertTrue(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "smb_multiuser_access")
        self.assertEqual(check["status"], "passed")
        self.assertTrue(check["values"]["initial_admin_smb_identity"])
        self.assertTrue(check["values"]["reader_write_denied"])
        self.assertTrue(check["values"]["unauthorized_share_hidden"])
        self.assertTrue(all(client.assertions.values()))
        self.assertEqual(set(client.users), {client.username})
        self.assertEqual(client.shares, {})
        self.assertEqual(sum(operation == "account_create" for operation, _ in client.actions), 2)
        self.assertEqual(sum(operation == "user_remove" for operation, _ in client.actions), 2)
        self.assertNotIn(client.username, json.dumps(report))

    def test_smb_without_initial_named_identity_blocks_account_and_share_creation(self):
        client = FakeGuest()
        original = client.request
        def request(path, body=None, expected_status=None):
            value = original(path, body, expected_status)
            if path == "/api/users":
                value["web"][0] = {**value["web"][0], "system_user": "titan-files"}
            return value
        client.request = request
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "smb_multiuser_access")
        self.assertIn("own enabled managed SMB identity", check["detail"])
        self.assertNotIn("share_create", [operation for operation, _ in client.actions])
        self.assertNotIn("account_create", [operation for operation, _ in client.actions])

    def test_failed_smb_probe_cleans_its_users_share_and_does_not_publish_credentials(self):
        client = FakeGuest()
        client.smb_access = Mock(side_effect=RuntimeError("private-password-and-smb-output"))
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        self.assertEqual(set(client.users), {client.username})
        self.assertEqual(client.shares, {})
        self.assertNotIn("private-password", json.dumps(report))
        check = next(item for item in report["checks"] if item["name"] == "smb_multiuser_access")
        self.assertEqual(check["status"], "failed")

    def test_invalid_fresh_debian_status_and_mutation_are_failures(self):
        mutations = [lambda value: value.update(rollback_available=True),
                     lambda value: value.update(automatic_reboot=True),
                     lambda value: value.update(reboot_scheduled=True),
                     lambda value: value.update(staged={"digest": "sha256:" + "b" * 64}),
                     lambda value: value["booted"].update(digest="private-invalid-digest")]
        for mutation in mutations:
            client = FakeGuest()
            original = client.request
            def request(path, body=None, expected_status=None):
                value = original(path, body, expected_status)
                if path == "/api/updates/system":
                    mutation(value)
                return value
            client.request = request
            with self.subTest(mutation=mutation):
                report = self.run_fixture(client)
                self.assertFalse(report["ok"])
                check = next(item for item in report["checks"] if item["name"] == "system_update_state_confirmation")
                self.assertEqual(check["status"], "failed")
                self.assertNotIn("private-invalid-digest", json.dumps(report))
        client = FakeGuest()
        original = client.request
        calls = 0
        def changed_after_rejection(path, body=None, expected_status=None):
            nonlocal calls
            value = original(path, body, expected_status)
            if path == "/api/updates/system":
                calls += 1
                if calls == 2:
                    value["reboot_scheduled"] = True
            return value
        client.request = changed_after_rejection
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        self.assertIn("changed", next(item for item in report["checks"] if item["name"] == "system_update_state_confirmation")["detail"])

    def test_custom_bridge_static_ip_restart_and_cleanup_are_exercised(self):
        client = FakeGuest()
        report = self.run_fixture(client)
        self.assertTrue(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "docker_custom_network_lifecycle")
        self.assertEqual(check["status"], "passed")
        self.assertTrue(check["values"]["initial_network"]["actual_static_ipv4"])
        self.assertTrue(check["values"]["restarted_network"]["published_lan_endpoint"])
        installs = [arguments for operation, arguments in client.actions if operation == "app_install"]
        self.assertNotIn("network", installs[0])
        self.assertEqual(installs[1]["network"]["ipv4_address"], "172.30.241.10")
        creation = next(arguments for operation, arguments in client.actions if operation == "app_network_create")
        removal = next(arguments for operation, arguments in client.actions if operation == "app_network_remove")
        self.assertEqual(creation["name"], removal["name"])
        self.assertEqual(removal["confirmation"], creation["name"])
        automatic_creation = next(arguments for operation, arguments in client.actions
                                  if operation == "app_network_create" and set(arguments) == {"name"})
        automatic_removal = next(arguments for operation, arguments in client.actions
                                 if operation == "app_network_remove" and arguments["name"] == automatic_creation["name"])
        self.assertEqual(automatic_removal, {"name": automatic_creation["name"], "confirmation": automatic_creation["name"]})
        self.assertFalse(automatic_creation["name"].startswith("titan-"))
        self.assertEqual(check["values"]["automatic_bridge"], {"name_only_create": True, "live_id_matches": True,
            "private_subnet_gateway": True, "no_existing_network_or_host_overlap": True, "remove": True})
        self.assertEqual(client.networks, {})
        self.assertIsNone(client.state)
        self.assertNotIn(creation["name"], json.dumps(report))
        self.assertNotIn(automatic_creation["name"], json.dumps(report))

    def test_name_only_network_rejects_wrong_live_identity_settings_and_addresses_with_cleanup(self):
        mutations = [lambda value: value.update(managed=False), lambda value: value.update(removable=False),
                     lambda value: value.update(scope="swarm"), lambda value: value.update(driver="host"),
                     lambda value: value.update(internal=True), lambda value: value.update(static_ipv4=False),
                     lambda value: value.update(id="private-invalid-id"), lambda value: value.update(containers=[{"name":"private-container"}]),
                     lambda value: value.update(used_by=["private-app"]), lambda value: value.update(subnets=[]),
                     lambda value: value["subnets"][0].update(subnet="8.8.8.0/24",gateway="8.8.8.1"),
                     lambda value: value["subnets"][0].update(subnet="172.30.0.0/16"),
                     lambda value: value["subnets"][0].update(subnet="10.0.2.0/24",gateway="10.0.2.1"),
                     lambda value: value["subnets"][0].update(gateway="172.30.0.255"),
                     lambda value: value["subnets"][0].update(gateway="172.31.0.1"),
                     lambda value: value["subnets"][0].update(subnet="private-invalid-subnet")]
        for mutation in mutations:
            client = FakeGuest()
            original = client.action
            def action(operation, arguments):
                result = original(operation, arguments)
                if operation == "app_network_create" and set(arguments) == {"name"}:
                    mutation(client.networks[arguments["name"]])
                return result
            client.action = action
            with self.subTest(mutation=mutation):
                report = self.run_fixture(client)
                check = next(item for item in report["checks"] if item["name"] == "docker_custom_network_lifecycle")
                self.assertEqual(check["status"], "failed")
                self.assertEqual(client.networks, {})
                self.assertIsNone(client.state)
                self.assertNotIn("private-", json.dumps(report))
                self.assertNotIn("automatic_bridge", check.get("values", {}))

    def test_name_only_network_rejects_existing_subnet_overlap_and_preserves_foreign_network(self):
        client = FakeGuest()
        foreign = {"name":"foreign", "driver":"bridge", "subnets":[{"family":4,"subnet":"172.31.5.0/24","gateway":"172.31.5.1"}]}
        client.networks["foreign"] = copy.deepcopy(foreign)
        original = client.action
        def action(operation, arguments):
            result = original(operation, arguments)
            if operation == "app_network_create" and set(arguments) == {"name"}:
                client.networks[arguments["name"]]["subnets"] = copy.deepcopy(foreign["subnets"])
            return result
        client.action = action
        report = self.run_fixture(client)
        check = next(item for item in report["checks"] if item["name"] == "docker_custom_network_lifecycle")
        self.assertEqual(check["status"], "failed")
        self.assertEqual(client.networks, {"foreign": foreign})
        self.assertNotIn("foreign", [arguments["name"] for operation, arguments in client.actions if operation == "app_network_remove"])

    def test_name_only_network_existing_name_is_not_reused_or_removed(self):
        client = FakeGuest()
        existing_name = "smoke-auto-01234567"
        existing = {"name":existing_name,"driver":"bridge","subnets":[]}
        client.networks[existing_name] = copy.deepcopy(existing)
        with patch.object(smoke.secrets, "token_hex", return_value="01234567"):
            report = self.run_fixture(client)
        check = next(item for item in report["checks"] if item["name"] == "docker_custom_network_lifecycle")
        self.assertEqual(check["status"], "failed")
        self.assertEqual(client.networks, {existing_name: existing})
        self.assertNotIn(existing_name, [arguments["name"] for operation, arguments in client.actions if operation.startswith("app_network_")])

    def test_name_only_network_failed_remove_retries_only_its_own_cleanup(self):
        client = FakeGuest()
        original = client.action
        attempts = 0
        def action(operation, arguments):
            nonlocal attempts
            if operation == "app_network_remove" and arguments["name"].startswith("smoke-auto-"):
                attempts += 1
                if attempts == 1:
                    raise smoke.SmokeFailure("Automatic removal fixture failed.")
            return original(operation, arguments)
        client.action = action
        report = self.run_fixture(client)
        check = next(item for item in report["checks"] if item["name"] == "docker_custom_network_lifecycle")
        self.assertEqual(check["status"], "failed")
        self.assertEqual(attempts, 2)
        self.assertEqual(client.networks, {})
        self.assertIsNone(client.state)

    def test_wrong_or_missing_actual_network_and_endpoint_fail_without_details_and_cleanup(self):
        mutations = [lambda value: value["networks"][0].update(ipv4="172.30.241.99"),
                     lambda value: value["networks"][0].update(gateway="172.30.241.2"),
                     lambda value: value["networks"][0].update(driver="host"),
                     lambda value: value.update(networks=[]),
                     lambda value: value.update(public_ip="private-address"),
                     lambda value: value.pop("public_ip"),
                     lambda value: value.update(endpoints=[]),
                     lambda value: value["endpoints"][0].update(scope="loopback"),
                     lambda value: value["endpoints"][0].update(url="http://private-token@10.0.2.15:18080/")]
        for mutation in mutations:
            client = FakeGuest()
            original = client.container
            def container():
                value = original()
                if client.app_network:
                    mutation(value)
                return value
            client.container = container
            with self.subTest(mutation=mutation):
                report = self.run_fixture(client)
                self.assertFalse(report["ok"])
                check = next(item for item in report["checks"] if item["name"] == "docker_custom_network_lifecycle")
                self.assertEqual(check["status"], "failed")
                self.assertEqual(client.networks, {})
                self.assertIsNone(client.state)
                self.assertNotIn("private-", json.dumps(report))

    def test_default_app_failure_skips_custom_network_without_mutating_it(self):
        client = FakeGuest()
        client.app_http_ready = Mock(side_effect=smoke.SmokeFailure("Default app failed."))
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "docker_custom_network_lifecycle")
        self.assertEqual(check["status"], "skipped")
        self.assertNotIn("app_network_create", [operation for operation, _ in client.actions])

    def test_created_network_must_report_requested_subnet_and_managed_state(self):
        mutations = [lambda network: network.update(managed=False),
                     lambda network: network.update(static_ipv4=False),
                     lambda network: network.update(internal=True),
                     lambda network: network["subnets"][0].update(subnet="172.30.242.0/24"),
                     lambda network: network["subnets"][0].update(gateway="172.30.241.2")]
        for mutation in mutations:
            client = FakeGuest()
            original = client.request
            def request(path, body=None, expected_status=None):
                value = original(path, body, expected_status)
                if path == "/api/app-networks" and value["networks"]:
                    mutation(value["networks"][0])
                return value
            client.request = request
            with self.subTest(mutation=mutation):
                report = self.run_fixture(client)
                self.assertFalse(report["ok"])
                check = next(item for item in report["checks"] if item["name"] == "docker_custom_network_lifecycle")
                self.assertEqual(check["status"], "failed")
                self.assertEqual(client.networks, {})
                installs = [arguments for operation, arguments in client.actions if operation == "app_install"]
                self.assertEqual(len(installs), 1)

    def test_invalid_catalog_and_personal_fields_fail_without_secret_output(self):
        mutations = [lambda value: value["apps"].pop(),
                     lambda value: value["apps"].append(value["apps"][0]),
                     lambda value: value["apps"][0].update(id='heimdall'),
                     lambda value: value["apps"][0]["first_login"].pop("instructions"),
                     lambda value: value["apps"][0]["first_login"].update(mode="unknown"),
                     lambda value: value["apps"][0]["first_login"].update(password="private-fixture-secret"),
                     lambda value: value["apps"][0].update(options={"password": "private-fixture-secret"}),
                     lambda value: value["apps"][0].update(environment={"TOKEN": "private-fixture-secret"}),
                     lambda value: value["apps"][0].update(install_schema=[{"key": "password", "default": "private-fixture-secret"}]),
                     lambda value: value["apps"][0].update(documentation="https://private-fixture-secret/"),
                     lambda value: value.update(options={"password": "private-fixture-secret"})]
        for mutation in mutations:
            client = FakeGuest()
            original = client.request
            payload = original("/api/catalog")
            mutation(payload)
            client.request = lambda path, body=None: payload if path == "/api/catalog" else original(path, body)
            with self.subTest(mutation=mutation):
                report = self.run_fixture(client)
                self.assertFalse(report["ok"])
                check = next(item for item in report["checks"] if item["name"] == "app_catalog_first_login")
                self.assertEqual(check["status"], "failed")
                self.assertNotIn("private-fixture-secret", json.dumps(report))
                self.assertEqual(next(item for item in report["checks"] if item["name"] == "docker_app_lifecycle")["status"], "passed")

    def test_kvm_domain_creation_start_stop_remove_are_exercised(self):
        client = FakeGuest(kvm=True)
        report = self.run_fixture(client)
        self.assertTrue(report["ok"])
        vm = next(check for check in report["checks"] if check["name"] == "vm_domain_lifecycle")
        self.assertEqual(vm["status"], "passed")
        self.assertFalse(vm["values"]["guest_os_boot"])
        self.assertIn("vm_remove", [operation for operation, _ in client.actions])
        self.assertIn(("console_assets", "running"),client.probes)
        self.assertEqual(client.probes[-1],("console_rfb","running"))
        self.assertTrue(vm["values"]["console"]["authenticated_websocket"])
        self.assertTrue(vm["values"]["direct_image_clone"]["source_metadata_unchanged"])
        creates = [arguments for operation, arguments in client.actions if operation == "vm_create"]
        self.assertEqual(len(creates), 3)
        self.assertEqual(creates[0]["firmware"], "uefi")
        self.assertTrue(vm["values"]["uefi_start"])
        self.assertEqual(creates[1]["disk_image"], "/var/lib/libvirt/images/titan/smoke-vm.qcow2")
        self.assertEqual(client.vms, {})

    def test_vm_source_revision_change_during_clone_fails_without_publishing_image_details(self):
        client = FakeGuest(kvm=True)
        original = client.request
        reads = 0
        def request(path, body=None, expected_status=None):
            nonlocal reads
            value = original(path, body, expected_status)
            if path.startswith("/api/vm-image-info?"):
                reads += 1
                if reads == 2:
                    value["revision"] = "b" * 64
                    value["path"] = "/private-user-secret/source.qcow2"
            return value
        client.request = request
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "vm_domain_lifecycle")
        self.assertEqual(check["status"], "failed")
        self.assertIn("source metadata changed", check["detail"])
        self.assertNotIn("private-user-secret", json.dumps(report))

    def test_vm_clone_must_retain_source_and_use_distinct_domain(self):
        for change in ({"source_retained": False}, {"id": "fixture-vm"},
                       {"disk_path": "/var/lib/libvirt/images/titan/smoke-vm.qcow2"}):
            client = FakeGuest(kvm=True)
            original = client.action
            def action(operation, arguments):
                value = original(operation, arguments)
                if operation == "vm_create" and arguments["name"] == "smoke-image-clone":
                    value.update(change)
                return value
            client.action = action
            with self.subTest(change=change):
                report = self.run_fixture(client)
                self.assertFalse(report["ok"])
                check = next(item for item in report["checks"] if item["name"] == "vm_domain_lifecycle")
                self.assertEqual(check["status"], "failed")
                self.assertIn("distinct managed", check["detail"])

    def test_existing_setup_blocks_all_mutation(self):
        client = Mock()
        client.request.return_value = {"setup_required": False, "demo": False, "user": None}
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        client.request.assert_called_once_with("/api/session")
        client.action.assert_not_called()

    def test_metrics_inconsistency_fails_report_without_hiding_component_checks(self):
        client = FakeGuest()
        original = client.request
        client.request = lambda path, body=None: ({"memory_total": 1000, "memory_used": 400,
            "memory_available": 700, "cpu_percent": 20, "demo": False} if path == "/api/status" else original(path, body))
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        self.assertEqual(next(check for check in report["checks"] if check["name"] == "cpu_ram_metrics")["status"], "failed")
        self.assertEqual(next(check for check in report["checks"] if check["name"] == "docker_app_lifecycle")["status"], "passed")

    def test_unexpected_secret_bearing_exception_is_not_in_report_or_stdout(self):
        client = FakeGuest()
        client.action = Mock(side_effect=RuntimeError("private-token-do-not-publish"))
        stream = io.StringIO()
        with patch.object(smoke.time, "sleep"), contextlib.redirect_stdout(stream):
            report = smoke.RuntimeSmoke(client).run()
        self.assertFalse(report["ok"])
        self.assertNotIn("private-token-do-not-publish", json.dumps(report) + stream.getvalue())

    def test_job_output_is_never_published_when_action_fails(self):
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{"job": "fixture-job"}, [{"id": "fixture-job", "status": "failed",
            "result": {"error": "password=private-fixture"}}]])
        with self.assertRaises(smoke.SmokeFailure) as caught:
            client.action("app_install", {"app": "heimdall"})
        self.assertNotIn("private-fixture", str(caught.exception))
        self.assertIn("Operation: app_install; category: unknown", str(caught.exception))

    def test_job_failure_identifies_permitted_action_and_fixed_category(self):
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{"job": "fixture-job"}, [{"id": "fixture-job", "status": "failed",
            "result": {"error": "Error response from daemon: port is already allocated; password=private-fixture",
                       "output": "Authorization: private-output"}}]])
        with self.assertRaises(smoke.SmokeFailure) as caught:
            client.action("app_action", {"app": "heimdall", "action": "start", "private": "private-argument"})
        self.assertEqual(str(caught.exception),
                         "Queued runtime action failed. Operation: app_action/start; category: port_conflict.")
        self.assertNotIn("private", str(caught.exception))

    def test_failed_install_collects_only_closed_read_only_observations(self):
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{"job": "fixture-job"}, [{"id": "fixture-job", "status": "failed",
            "result": {"error": "Container-Netzwerk weicht von der verwalteten Standardvorlage ab. private-token",
                       "output": "private-output"}}], {"app": {"state": "blocked", "last_error": "private-error"},
            "logs": "private-logs", "container": {"state": "created", "Env": ["PASSWORD=private-password"]}}])
        client.guest_diagnostic = Mock(return_value={"available": True, "container_state": "created",
            "network_mode_category": "compose_default", "attached_network_category": "none"})
        with self.assertRaises(smoke.SmokeFailure) as caught:
            client.action("app_install", {"app": "heimdall", "password": "private-argument"})
        self.assertEqual(caught.exception.values["error_category"], "app_network_validation")
        self.assertEqual(caught.exception.values["app"]["state"], "created")
        self.assertEqual(caught.exception.values["guest"]["attached_network_category"], "none")
        self.assertNotIn("private", str(caught.exception) + json.dumps(caught.exception.values))
        client.request.assert_called_with("/api/app-details?app=heimdall&tail=50")
        client.guest_diagnostic.assert_called_once_with()

    def test_failed_install_preserves_failure_when_read_only_diagnostics_are_unavailable(self):
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{"job": "fixture-job"}, [{"id": "fixture-job", "status": "failed",
            "result": {"error": "private-error"}}], RuntimeError("private-api-error")])
        client.guest_diagnostic = Mock(side_effect=RuntimeError("private-terminal-error"))
        with self.assertRaises(smoke.SmokeFailure) as caught:
            client.action("app_install", {"app": "heimdall"})
        self.assertEqual(caught.exception.values, {"error_category": "unknown",
            "app": {"available": False}, "guest": {"available": False}})
        self.assertNotIn("private", str(caught.exception) + json.dumps(caught.exception.values))

    def test_failed_stack_install_observes_only_the_actual_stack_and_redacts_memory_error(self):
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{"job": "fixture-job"}, [{"id": "fixture-job", "status": "failed",
            "result": {"error": "Die Containergrenzen und die NAS-Reserve passen momentan nicht sicher in den Arbeitsspeicher. private-token",
                       "output": "private-output"}}], {"app": {"state": "blocked"}, "logs": "private-logs"}])
        client.guest_diagnostic = Mock()
        with self.assertRaises(smoke.SmokeFailure) as caught:
            client.action("app_install", {"app": smoke.RUNTIME_STACK_ID})
        self.assertEqual(caught.exception.values["error_category"], "memory_budget")
        self.assertEqual(caught.exception.values["app"]["state"], "blocked")
        self.assertNotIn("guest", caught.exception.values)
        client.request.assert_called_with("/api/app-details?app=" + smoke.RUNTIME_STACK_ID + "&tail=50")
        client.guest_diagnostic.assert_not_called()
        self.assertNotIn("private", str(caught.exception) + json.dumps(caught.exception.values))

    def test_unknown_install_identity_cannot_trigger_an_unrelated_guest_diagnostic(self):
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{"job": "fixture-job"}, [{"id": "fixture-job", "status": "failed",
            "result": {"error": "RAM-Engpass private-error"}}]])
        client.guest_diagnostic = Mock()
        with self.assertRaises(smoke.SmokeFailure) as caught:
            client.action("app_install", {"app": "private-app"})
        self.assertEqual(caught.exception.values, {"error_category": "memory_budget"})
        self.assertEqual(client.request.call_count, 2)
        client.guest_diagnostic.assert_not_called()
        self.assertNotIn("private", str(caught.exception) + json.dumps(caught.exception.values))

    def test_job_failure_does_not_echo_unknown_operation_or_action(self):
        for operation, arguments, label in (("private-operation", {"action": "private-action"}, "runtime_action"),
                                            ("app_action", {"action": "private-action"}, "app_action")):
            client = smoke.GuestClient()
            client.request = Mock(side_effect=[{"job": "fixture-job"}, [{"id": "fixture-job", "status": "failed",
                "result": {"error": "https://private-url/path?token=private-token"}}]])
            with self.assertRaises(smoke.SmokeFailure) as caught:
                client.action(operation, arguments)
            self.assertEqual(str(caught.exception), f"Queued runtime action failed. Operation: {label}; category: unknown.")
            self.assertNotIn("private", str(caught.exception))

    def test_job_wait_is_bounded(self):
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{"job": "fixture-job"}, [{"id": "fixture-job", "status": "running"}]])
        with patch.object(smoke.time, "monotonic", side_effect=[0, 0, 301]), patch.object(smoke.time, "sleep"):
            with self.assertRaisesRegex(smoke.SmokeFailure, "deadline"):
                client.action("app_install", {"app": "heimdall"})

    def test_http_readiness_failure_fails_the_container_check(self):
        client = FakeGuest()
        client.app_http_ready = Mock(side_effect=smoke.SmokeFailure("Heimdall HTTP page did not become ready within the bounded deadline."))
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        app = next(item for item in report["checks"] if item["name"] == "docker_app_lifecycle")
        self.assertEqual(app["status"], "failed")
        self.assertIn("HTTP page", app["detail"])

    def test_console_transport_failure_is_never_a_successful_vm_check(self):
        client = FakeGuest(kvm=True)
        client.console_rfb = Mock(side_effect=smoke.SmokeFailure("Authenticated VM console WebSocket upgrade failed."))
        report = self.run_fixture(client)
        self.assertFalse(report["ok"])
        vm = next(item for item in report["checks"] if item["name"] == "vm_domain_lifecycle")
        self.assertEqual(vm["status"], "failed")
        self.assertIn("WebSocket", vm["detail"])

    def test_transport_is_fixed_loopback_and_guest_host_origin(self):
        response = Mock(status=200)
        response.read.return_value = b'{"ok":true}'
        response.getheader.return_value = None
        with patch.object(smoke.http.client, "HTTPSConnection") as connection:
            connection.return_value.getresponse.return_value = response
            client = smoke.GuestClient()
            self.assertEqual(client.request("/api/session"), {"ok": True})
        args, kwargs = connection.call_args
        self.assertEqual(args, ("127.0.0.1", 15000))
        headers = connection.return_value.request.call_args.args[3]
        self.assertEqual(headers["Host"], "10.0.2.15")
        self.assertEqual(headers["Origin"], "https://10.0.2.15")
        self.assertEqual(kwargs["timeout"], 30)

    def test_legacy_transport_is_selected_before_sending_a_mutating_request(self):
        unavailable, legacy = Mock(), Mock()
        unavailable.connect.side_effect = ConnectionRefusedError()
        response = Mock(status=200); response.read.return_value = b'{"ok":true}'; response.getheader.return_value = None
        legacy.getresponse.return_value = response
        with patch.object(smoke.http.client,'HTTPSConnection',side_effect=[unavailable,legacy]) as connections:
            client = smoke.GuestClient()
            self.assertEqual(client.request('/api/actions',{'operation':'test'}), {'ok':True})
        unavailable.request.assert_not_called()
        legacy.request.assert_called_once()
        self.assertEqual(connections.call_args_list[1].args, ('127.0.0.1',15001))
        self.assertEqual(legacy.request.call_args.args[3]['Origin'], 'https://10.0.2.15:5000')
        self.assertEqual(client.forward_port,15001)

    def test_post_is_never_retried_after_the_request_may_have_been_sent(self):
        with patch.object(smoke.http.client,'HTTPSConnection') as connections:
            connections.return_value.request.side_effect = ConnectionResetError()
            with self.assertRaises(smoke.SmokeFailure): smoke.GuestClient().request('/api/actions',{'operation':'test'})
            self.assertEqual(connections.call_count,1)
            connections.return_value.request.assert_called_once()

    def test_expected_rejection_status_is_enforced_by_fixed_transport(self):
        for status in (400, 200, 409):
            response = Mock(status=status)
            response.read.return_value = b'{"error":"private-fixture"}'
            response.getheader.return_value = None
            with self.subTest(status=status), patch.object(smoke.http.client, "HTTPSConnection") as connection:
                connection.return_value.getresponse.return_value = response
                client = smoke.GuestClient()
                if status == 400:
                    self.assertEqual(client.request("/api/actions", {"confirmation": "INVALID"}, expected_status=400),
                                     {"error": "private-fixture"})
                else:
                    with self.assertRaises(smoke.SmokeFailure) as caught:
                        client.request("/api/actions", {"confirmation": "INVALID"}, expected_status=400)
                    self.assertNotIn("private-fixture", str(caught.exception))

    def test_mutating_cli_requires_ci_and_explicit_disposable_confirmation(self):
        for environment, arguments in (({}, ["--confirm-disposable-guest"]), ({"GITHUB_ACTIONS": "true"}, [])):
            with patch.dict(smoke.os.environ, environment, clear=True), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    smoke.main(arguments)
            self.assertEqual(caught.exception.code, 2)

    def test_cli_writes_only_sanitized_report_and_propagates_failure(self):
        report = {"format": "titan-runtime-smoke-v1", "ok": False, "checks": [{"name": "cpu_ram_metrics", "status": "failed"}]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(smoke.os.environ, {"GITHUB_ACTIONS": "true"}), \
                patch.object(smoke, "RuntimeSmoke") as suite:
            suite.return_value.run.return_value = report
            path = Path(directory) / "runtime-test.json"
            self.assertEqual(smoke.main(["--confirm-disposable-guest", "--qmp-socket", "/tmp/titan-image-smoke.12345678/qmp.sock", "--report", str(path)]), 1)
            self.assertEqual(json.loads(path.read_text()), report)


class RuntimeSMBTransportTests(unittest.TestCase):
    writer = ("smoke-1234abcd", "private-writer-token")
    reader = ("smoke-r-1234abcd", "private-reader-token")
    outsider = ("smoke-n-1234abcd", "private-outsider-token")
    share = "smoke-share-1234abcd"

    def successful_process(self, arguments, **kwargs):
        self.assertEqual(kwargs["timeout"], 15)
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(set(kwargs["env"]), {"PATH", "LC_ALL"})
        self.assertEqual(arguments[arguments.index("-I") + 1], "127.0.0.1")
        self.assertEqual(arguments[arguments.index("-p") + 1], "15445")
        self.assertNotIn("-U", arguments)
        authentication = Path(arguments[arguments.index("-A") + 1])
        self.auth_paths.append(authentication)
        self.assertEqual(authentication.stat().st_mode & 0o777, 0o600)
        self.assertIn("password = private-", authentication.read_text())
        for _, password in (self.writer, self.reader, self.outside_identity):
            self.assertNotIn(password, str(arguments))
        if "-L" in arguments:
            return SimpleNamespace(returncode=0, stdout="IPC|IPC$|IPC Service\n", stderr="private-unused-output")
        command = arguments[arguments.index("-c") + 1]
        tokens = shlex.split(command.replace(";", " ; "))
        if "denied.txt" in tokens or command == "ls":
            return SimpleNamespace(returncode=1, stdout="NT_STATUS_ACCESS_DENIED", stderr="private-unused-output")
        if "get" in tokens:
            download = Path(tokens[tokens.index("get") + 2])
            if "put" in tokens:
                self.payload = Path(tokens[tokens.index("put") + 1]).read_bytes()
            download.write_bytes(self.payload)
        return SimpleNamespace(returncode=0, stdout="private-unused-output", stderr="")

    def setUp(self):
        self.auth_paths = []
        self.outside_identity = self.outsider

    def probe(self):
        return smoke.GuestClient.smb_access(self.writer, self.reader, self.outsider, self.share)

    def test_credential_files_private_fixed_transport_and_all_roles_proved_without_output(self):
        with patch.object(smoke.subprocess, "run", side_effect=self.successful_process) as command:
            value = self.probe()
        self.assertEqual(command.call_count, 6)
        self.assertTrue(all(value.values()))
        self.assertTrue(value["unauthorized_share_hidden"])
        self.assertNotIn("private", json.dumps(value))
        self.assertTrue(self.auth_paths)
        self.assertTrue(all(not path.exists() for path in self.auth_paths))

    def test_smb_process_timeout_is_bounded_and_never_echoes_command_or_output(self):
        exception = smoke.subprocess.TimeoutExpired(["smbclient", "private-password"], 15,
            output="private-output", stderr="private-stderr")
        with patch.object(smoke.subprocess, "run", side_effect=exception) as command:
            with self.assertRaises(smoke.SmokeFailure) as caught:
                self.probe()
        self.assertEqual(command.call_count, 1)
        self.assertIn("deadline", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))

    def test_transport_readiness_retries_are_capped_at_three(self):
        refused = SimpleNamespace(returncode=1, stdout="NT_STATUS_CONNECTION_REFUSED private-output", stderr="")
        with patch.object(smoke.subprocess, "run", return_value=refused) as command, patch.object(smoke.time, "sleep") as delay:
            with self.assertRaises(smoke.SmokeFailure) as caught:
                self.probe()
        self.assertEqual(command.call_count, 3)
        self.assertEqual(delay.call_count, 2)
        self.assertNotIn("private-output", str(caught.exception))

    def test_initial_transport_can_recover_without_retrying_permission_failures(self):
        calls = 0
        def process(arguments, **kwargs):
            nonlocal calls
            calls += 1
            if calls <= 2:
                return SimpleNamespace(returncode=1, stdout="NT_STATUS_CONNECTION_REFUSED", stderr="")
            return self.successful_process(arguments, **kwargs)
        with patch.object(smoke.subprocess, "run", side_effect=process) as command, patch.object(smoke.time, "sleep") as delay:
            self.assertTrue(self.probe()["writer_read_write"])
        self.assertEqual(command.call_count, 8)
        self.assertEqual(delay.call_count, 2)

    def test_unknown_failure_does_not_count_as_a_readonly_access_denial(self):
        def process(arguments, **kwargs):
            if "-c" in arguments and "denied.txt" in arguments[-1]:
                return SimpleNamespace(returncode=1, stdout="NT_STATUS_LOGON_FAILURE private-password", stderr="")
            return self.successful_process(arguments, **kwargs)
        with patch.object(smoke.subprocess, "run", side_effect=process):
            with self.assertRaises(smoke.SmokeFailure) as caught:
                self.probe()
        self.assertIn("explicit write denial", str(caught.exception))
        self.assertNotIn("private-password", str(caught.exception))

    def test_visible_private_share_and_corrupted_download_each_fail(self):
        for failure in ("enumeration", "download"):
            def process(arguments, **kwargs):
                result = self.successful_process(arguments, **kwargs)
                if failure == "enumeration" and "-L" in arguments:
                    return SimpleNamespace(returncode=0, stdout="Disk|" + self.share + "|private-comment\n", stderr="")
                if failure == "download" and "-c" in arguments and "get" in arguments[-1]:
                    tokens = shlex.split(arguments[-1].replace(";", " ; "))
                    Path(tokens[tokens.index("get") + 2]).write_bytes(b"wrong bytes")
                return result
            with self.subTest(failure=failure), patch.object(smoke.subprocess, "run", side_effect=process):
                with self.assertRaises(smoke.SmokeFailure) as caught:
                    self.probe()
                self.assertNotIn("private-comment", str(caught.exception))

    def test_bad_smoke_identity_or_share_blocks_execution(self):
        for writer, share in ((("private-real-user", "password"), self.share), (self.writer, "existing-share"),
                              ((self.writer[0], "password\nvalue"), self.share)):
            with self.subTest(share=share), patch.object(smoke.subprocess, "run") as command:
                with self.assertRaises(smoke.SmokeFailure):
                    smoke.GuestClient.smb_access(writer, self.reader, self.outsider, share)
                command.assert_not_called()


class MemoryTransport:
    def __init__(self, incoming):
        self.incoming = bytearray(incoming)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, value):
        self.timeout = value

    def recv(self, count):
        # Split reads deliberately to exercise HTTP/frame boundary handling.
        result = bytes(self.incoming[:min(count, 7)])
        del self.incoming[:len(result)]
        return result

    def sendall(self, data):
        self.sent.append(data)


def server_frame(data, opcode=2, final=True):
    flags = (0x80 if final else 0) | opcode
    if len(data) < 126:
        return bytes([flags, len(data)]) + data
    return bytes([flags, 126]) + struct.pack("!H", len(data)) + data


def rfb_fixture():
    pixel = bytes([32, 24, 0, 1]) + struct.pack("!HHH", 255, 255, 255) + bytes([16, 8, 0, 0, 0, 0])
    return b"RFB 003.008\n" + b"\x01\x01" + bytes(4) + struct.pack("!HH", 640, 480) + pixel + struct.pack("!I", 7) + b"fixture"


def client_frame_payload(frame):
    length = frame[1] & 127
    mask = frame[2:6]
    return bytes(value ^ mask[index % 4] for index, value in enumerate(frame[6:6 + length]))


class RuntimeTransportTests(unittest.TestCase):
    def test_stack_diagnostics_keep_only_known_services_and_closed_states(self):
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{'services': [
            {'id': smoke.RUNTIME_STACK_ID + '-sidecar',
             'container': {'state': 'restarting', 'exit_code': 1, 'Env': ['PASSWORD=private-secret']},
             'warning': 'private-warning'},
            {'id': 'private-unrelated-container', 'container': {'state': 'running'}}]},
            {'logs': 'Permission denied: private-path private-secret'}])
        value = client.stack_diagnostic()
        self.assertEqual(set(value['services']), {'sidecar'})
        self.assertEqual(value['services']['sidecar']['state'], 'restarting')
        self.assertEqual(value['services']['sidecar']['log_error_category'], 'filesystem_permissions')
        self.assertNotIn('private', json.dumps(value))
        self.assertEqual(client.request.call_count, 2)
        client.request.assert_called_with('/api/package-logs?app=' + smoke.RUNTIME_STACK_ID + '&service=' + smoke.RUNTIME_STACK_ID + '-sidecar&tail=50')

    def test_stack_diagnostic_failure_never_replaces_or_discloses_install_failure(self):
        client = smoke.GuestClient()
        client.request = Mock(side_effect=RuntimeError('private-secret'))
        self.assertEqual(client.stack_diagnostic(), {'available': False})
        self.assertEqual(smoke.error_category({'error': 'dependency failed to start: container private-secret is unhealthy'}), 'dependency_health')

    def test_error_categories_cover_distinct_failures_without_echoing_values(self):
        errors = {
            "memory_budget": "Die Containergrenzen und die NAS-Reserve passen momentan nicht sicher in den Arbeitsspeicher. private-value",
            "registry_rate_limit": "Error: TOOMANYREQUESTS: private-registry pull rate limit exceeded",
            "registry_auth": "Error: unauthorized: private-registry requires private-password",
            "registry_network": "Get https://private-url: dial tcp: lookup registry: no such host",
            "disk_space": "failed to extract private-layer: no space left on device",
            "bind_mount": "invalid mount config for type bind: private-path",
            "port_conflict": "private-address: address already in use",
            "container_runtime": "OCI runtime create failed: private-container",
            "config_validation": "validating private-file: additional property private-field is not allowed",
            "app_network_validation": "Container-Netzwerk weicht von der verwalteten Standardvorlage ab. private-name",
            "selinux_label": "Docker liefert kein gültiges privates SELinux-Label für die App-Konfiguration. private-label",
            "config_parent_permissions": "Elternverzeichnis der App-Konfiguration ist nicht geschützt. private-path",
            "config_unsafe_path": "App-Verzeichnis fehlt oder enthält einen symbolischen Link. private-path",
            "docker_api_schema": "Docker liefert ungültige App-Details. private-inspect",
            "filesystem_permissions": "chcon: private-path: Operation not permitted",
            "command_timeout": "docker antwortet nicht innerhalb von 600 Sekunden. Dienststatus prüfen. private-token",
            "missing_component": "chcon ist nicht installiert. private-path",
            "service_identity": "getpwnam(): name not found: 'titan-files' private-token",
            "unknown": "unknown private-diagnostic private-token",
        }
        for category, error in errors.items():
            with self.subTest(category=category):
                self.assertEqual(smoke.error_category({"error": error, "output": "private-log"}), category)

    def test_error_classifier_reads_only_bounded_error_string(self):
        self.assertEqual(smoke.error_category({"error": "unauthorized" + "x" * 4000}), "unknown")
        self.assertEqual(smoke.error_category({"error": "x" * 5000 + "no space left on device"}), "disk_space")
        for value in (None, "no such host", [], {"output": "unauthorized"}, {"error": {"password": "unauthorized"}}):
            self.assertEqual(smoke.error_category(value), "unknown")

    def test_memory_failures_use_a_closed_category_without_exposing_counters_or_paths(self):
        messages = ("Der Kernel meldet einen aktuellen RAM-Engpass.",
                    "Ein laufender Docker-Container hat kein gültiges RAM-Limit.",
                    "Gültige RAM-Messwerte fehlen.",
                    "Der verfügbare Arbeitsspeicher ist nicht messbar.",
                    "Der RAM-Bedarf laufender virtueller Maschinen ist nicht sicher ermittelbar.",
                    "Ungültiges VM-RAM-Budget.")
        for message in messages:
            with self.subTest(message=message):
                category = smoke.error_category({"error": message + " private-path private-token", "output": "private-output"})
                self.assertEqual(category, "memory_budget")

    def test_action_labels_allow_only_fixed_smoke_values(self):
        for arguments in ({"action": "private-action"}, {"action": {"password": "private-value"}}, None):
            self.assertEqual(smoke.action_label("app_action", arguments), "app_action")
        self.assertEqual(smoke.action_label("vm_action", {"action": "poweroff", "vm": "private-vm"}), "vm_action/poweroff")
        self.assertEqual(smoke.action_label("app_install", {"action": "start"}), "app_install")

    def test_http_app_probe_uses_only_fixed_forward_and_checks_real_page(self):
        response = Mock(status=200)
        response.read.return_value = b"<!doctype html><title>Heimdall</title>"
        response.getheader.return_value = "text/html; charset=UTF-8"
        with patch.object(smoke.http.client, "HTTPConnection") as connection:
            connection.return_value.getresponse.return_value = response
            self.assertEqual(smoke.GuestClient().app_http_ready(), {"http_status": 200, "app_page": True})
        connection.assert_called_once_with("127.0.0.1", 15080, timeout=5)
        connection.return_value.request.assert_called_once_with("GET", "/", headers={"Host": "10.0.2.15:18080"})
        response.read.assert_called_once_with(1024 * 1024 + 1)

    def test_nextcloud_probe_uses_fixed_login_page_and_rejects_unknown_apps(self):
        response = Mock(status=200)
        response.read.return_value = b"<!doctype html><title>Nextcloud</title>"
        response.getheader.return_value = "text/html"
        with patch.object(smoke.http.client, "HTTPConnection") as connection:
            connection.return_value.getresponse.return_value = response
            self.assertTrue(smoke.GuestClient().app_http_ready(expected_app="nextcloud")["app_page"])
            connection.return_value.request.assert_called_once_with(
                "GET", "/index.php/login", headers={"Host": "10.0.2.15:18080"})
        with patch.object(smoke.http.client, "HTTPConnection") as connection:
            with self.assertRaisesRegex(smoke.SmokeFailure, "Unknown runtime"):
                smoke.GuestClient().app_http_ready(expected_app="https://external.invalid")
            connection.assert_not_called()

    def test_http_redirects_and_wrong_pages_do_not_pass_or_leak_response(self):
        for status, page in ((302, b"private-location"), (200, b"private-login-error")):
            response = Mock(status=status)
            response.read.return_value = page
            response.getheader.return_value = "text/html"
            with patch.object(smoke.http.client, "HTTPConnection") as connection, \
                    patch.object(smoke.time, "monotonic", side_effect=[0, 0, 121]), patch.object(smoke.time, "sleep"):
                connection.return_value.getresponse.return_value = response
                client = smoke.GuestClient()
                client.request = Mock(return_value={"app": {"state": "running"}, "logs": "private-log"})
                with self.assertRaisesRegex(smoke.SmokeFailure, "bounded deadline") as caught:
                    client.app_http_ready()
                self.assertNotIn("private", str(caught.exception))
                self.assertNotIn("private", json.dumps(caught.exception.values))
                self.assertEqual(connection.call_count, 1)

    def test_http_failure_retains_only_status_type_and_safe_app_observation(self):
        response = Mock(status=502)
        response.read.return_value = b"private-response-with-cookie"
        response.getheader.return_value = "text/html; private-parameter=private-value"
        client = smoke.GuestClient()
        client.request = Mock(return_value={"app": {"state": "running", "last_error": "private-app-error"},
            "container": {"state": "running", "health": "", "restarts": 0, "exit_code": 0,
                          "ports": [{"port": 18080, "target": 80, "protocol": "tcp", "host": "private-host"}]},
            "logs": "[ls.io-init] done.\nPHP Fatal error: private-file private-token"})
        with patch.object(smoke.http.client, "HTTPConnection") as connection, \
                patch.object(smoke.time, "monotonic", side_effect=[0, 0, 121]), patch.object(smoke.time, "sleep"):
            connection.return_value.getresponse.return_value = response
            with self.assertRaises(smoke.SmokeFailure) as caught:
                client.app_http_ready()
        observed = caught.exception.values
        self.assertEqual(observed["last_http_status"], 502)
        self.assertEqual(observed["last_content_type"], "text/html")
        self.assertEqual(observed["last_transport"], "http_response")
        self.assertEqual(observed["app"]["state"], "running")
        self.assertTrue(observed["app"]["port_18080_tcp_to_80"])
        self.assertEqual(observed["app"]["log_categories"], ["php_error", "startup_complete"])
        self.assertNotIn("private", json.dumps(observed))
        client.request.assert_any_call("/api/app-details?app=heimdall&tail=50")

    def test_http_transport_errors_have_fixed_categories_and_no_raw_exceptions(self):
        for error, category in ((ConnectionRefusedError("private-refusal"), "connection_refused"),
                                (TimeoutError("private-timeout"), "timeout"),
                                (ConnectionResetError("private-reset"), "connection_reset"),
                                (OSError("private-os-error"), "os_error"),
                                (smoke.http.client.BadStatusLine("private-header"), "http_protocol")):
            client = smoke.GuestClient()
            client.request = Mock(side_effect=RuntimeError("private-diagnostic-error"))
            with patch.object(smoke.http.client, "HTTPConnection") as connection, \
                    patch.object(smoke.time, "monotonic", side_effect=[0, 0, 121]), patch.object(smoke.time, "sleep"):
                connection.return_value.request.side_effect = error
                with self.assertRaises(smoke.SmokeFailure) as caught:
                    client.app_http_ready()
            self.assertEqual(caught.exception.values["last_transport"], category)
            self.assertEqual(caught.exception.values["app"], {"available": False})
            self.assertNotIn("private", str(caught.exception) + json.dumps(caught.exception.values))

    def test_untrusted_mime_type_and_app_fields_cannot_escape_closed_vocabulary(self):
        response = Mock(status=200)
        response.read.return_value = b"Heimdall private-response"
        response.getheader.return_value = "private/mime-token"
        client = smoke.GuestClient()
        client.request = Mock(return_value={"app": {"state": "private-state"}, "container": {
            "state": "private-state", "health": "private-health", "restarts": "private-restarts", "exit_code": 300},
            "logs": "nginx: configuration file /private-file syntax is ok"})
        with patch.object(smoke.http.client, "HTTPConnection") as connection, \
                patch.object(smoke.time, "monotonic", side_effect=[0, 0, 121]), patch.object(smoke.time, "sleep"):
            connection.return_value.getresponse.return_value = response
            with self.assertRaises(smoke.SmokeFailure) as caught:
                client.app_http_ready()
        observed = caught.exception.values
        self.assertEqual(observed["last_content_type"], "other")
        self.assertEqual(observed["response_category"], "unexpected_page")
        self.assertEqual(observed["app"]["state"], "unknown")
        self.assertEqual(observed["app"]["log_categories"], [])
        self.assertIsNone(observed["app"]["exit_code"])
        self.assertNotIn("private", json.dumps(observed))

    def test_app_log_categories_read_only_bounded_tail(self):
        details = {"logs": "Permission denied" + "x" * 8192 + "[ls.io-init] done."}
        self.assertEqual(smoke.app_observation(details)["log_categories"], ["startup_complete"])
        self.assertEqual(smoke.app_observation(None), {"available": False})

    def test_failed_service_operation_and_path_scope_are_closed_and_relevant(self):
        details = {"logs": "init-nginx completed\nmkdir: cannot create directory '/config/private-dir': Permission denied\n"
            "s6-rc: warning: unable to start service init-folders: command exited 1\n"
            "private-service: write /private-path/private-token: Permission denied\n"
            "init-heimdall-configured-other: completed"}
        result = smoke.app_observation(details)
        self.assertEqual(result["failed_services"], ["init-folders"])
        self.assertEqual(result["error_operations"], ["mkdir", "write"])
        self.assertEqual(result["error_path_scopes"], ["/config"])
        self.assertNotIn("private", json.dumps(result))

    def test_prepared_guest_command_reports_label_mismatch_without_raw_inspect_or_stderr(self):
        import os, pwd, stat, subprocess
        owner = SimpleNamespace(pw_uid=77, pw_gid=88)
        metadata = SimpleNamespace(st_uid=77, st_gid=88, st_mode=stat.S_IFDIR | 0o750)
        inspect = SimpleNamespace(returncode=0, stdout=json.dumps([{
            "MountLabel": "system_u:object_r:container_file_t:s0:c10,c20",
            "Mounts": [{"Destination": "/config", "Source": "/var/lib/titan-agent/apps/heimdall/config"}],
            "Config": {"Env": ["PASSWORD=private-token"]}}]))
        curl = SimpleNamespace(returncode=56, stdout="000 ", stderr="private-network-error")
        stream = io.StringIO()
        with patch.object(os, "stat", return_value=metadata), patch.object(os, "getxattr", return_value=b"system_u:object_r:var_lib_t:s0\0"), \
                patch.object(pwd, "getpwnam", return_value=owner), patch.object(Path, "read_text", return_value="1"), \
                patch.object(subprocess, "run", side_effect=[inspect, curl]) as run, contextlib.redirect_stdout(stream):
            exec(compile(smoke.GUEST_DIAGNOSTIC, "<fixed guest diagnostic>", "exec"), {})
        self.assertNotIn("private", stream.getvalue())
        value = json.loads(stream.getvalue().partition(":")[2])
        self.assertEqual(value["config_selinux_type"], "var_lib_t")
        self.assertTrue(value["mount_label_container_file"])
        self.assertFalse(value["config_mcs_matches_mount"])
        self.assertTrue(value["config_is_expected_bind"])
        self.assertTrue(value["config_owner_matches"])
        self.assertEqual(value["curl_category"], "connection_reset")
        self.assertEqual(run.call_args_list[0].args[0], ["docker", "inspect", "--type", "container", "titan-heimdall"])
        self.assertEqual(run.call_args_list[1].args[0][-1], "http://127.0.0.1:18080/")
        self.assertIn("--output", run.call_args_list[1].args[0])

    def test_guest_observation_rejects_unknown_keys_and_values(self):
        value = smoke.guest_observation({"available": True, "config_selinux_type": "private-type",
            "config_owner_matches": "private-value", "http_status": "private-status", "config_mode": 0o10000,
            "curl_category": "private-error", "content_type": "private-mime", "private-key": "private-token"})
        self.assertNotIn("private", json.dumps(value))
        self.assertEqual(value["config_selinux_type"], "other")
        self.assertIsNone(value["config_mode"])
        self.assertIsNone(value["http_status"])

    def test_guest_network_and_container_observation_rejects_private_values_and_wrong_types(self):
        value = smoke.guest_observation({"available": True, "container_present": "private-value",
            "container_state": "private-state", "network_mode_category": "private-network",
            "attached_network_category": "private-network-name", "container_identity_matches": True,
            "container_mounts_match": False, "MountLabel": "private-label", "private-key": "private-value"})
        self.assertNotIn("private", json.dumps(value))
        self.assertEqual(value["container_state"], "unknown")
        self.assertEqual(value["network_mode_category"], "other")
        self.assertEqual(value["attached_network_category"], "other")
        self.assertNotIn("container_present", value)
        self.assertTrue(value["container_identity_matches"])
        self.assertFalse(value["container_mounts_match"])

    def test_prepared_guest_command_distinguishes_created_network_mode_and_missing_attachment(self):
        import os, pwd, stat, subprocess
        metadata = SimpleNamespace(st_uid=0, st_gid=0, st_mode=stat.S_IFDIR | 0o700)
        label = "system_u:object_r:container_file_t:s0:c10,c20"
        for mode, networks, expected_mode, expected_attached, has_ids, has_static in (
                ("titan-heimdall_default", {}, "compose_default", "none", False, False),
                ("a" * 64, {"titan-heimdall_default": {"NetworkID": "a" * 64}}, "network_id", "compose_default", True, False),
                ("private-network", {"private-network": {"NetworkID": "private-id"}}, "other", "other", False, False),
                ("private-network", {"private-network": {"NetworkID": "", "IPAMConfig": {"IPv4Address": "172.30.241.10"}}},
                 "other", "other", False, True)):
            container = {"Name": "/titan-heimdall", "State": {"Status": "created"}, "MountLabel": label,
                "Config": {"Image": "lscr.io/linuxserver/heimdall:latest", "Env": ["PASSWORD=private-secret"],
                    "Labels": {"io.titan.managed": "true", "io.titan.app": "heimdall",
                        "com.docker.compose.project": "titan-heimdall", "com.docker.compose.service": "heimdall"}},
                "HostConfig": {"NetworkMode": mode, "PortBindings": {"80/tcp": [{"HostIp": "", "HostPort": "18080"}]}},
                "NetworkSettings": {"Networks": networks}, "Mounts": [{"Type": "bind", "Destination": "/config",
                    "Source": "/var/lib/titan-agent/apps/heimdall/config"}]}
            inspect = SimpleNamespace(returncode=0, stdout=json.dumps([container]), stderr="private-stderr")
            curl = SimpleNamespace(returncode=7, stdout="000 ", stderr="private-stderr")
            stream = io.StringIO()
            with self.subTest(mode=mode), patch.object(os, "stat", return_value=metadata), \
                    patch.object(os, "getxattr", return_value=label.encode()), \
                    patch.object(pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=0, pw_gid=0)), \
                    patch.object(Path, "read_text", return_value="1"), \
                    patch.object(subprocess, "run", side_effect=[inspect, curl]) as run, contextlib.redirect_stdout(stream):
                exec(compile(smoke.GUEST_DIAGNOSTIC, "<fixed guest diagnostic>", "exec"), {})
            value = smoke.guest_observation(json.loads(stream.getvalue().partition(":")[2]))
            self.assertNotIn("private", stream.getvalue())
            self.assertTrue(value["container_present"])
            self.assertEqual(value["container_state"], "created")
            self.assertEqual(value["network_mode_category"], expected_mode)
            self.assertEqual(value["attached_network_category"], expected_attached)
            self.assertEqual(value["attached_network_ids_present"], has_ids)
            self.assertEqual(value["smoke_static_ipv4_configured"], has_static)
            self.assertTrue(value["config_parents_protected"])
            self.assertTrue(value["container_identity_matches"])
            self.assertTrue(value["container_ports_match"])
            self.assertTrue(value["container_mounts_match"])
            self.assertTrue(value["mount_label_valid"])
            self.assertTrue(value["config_mcs_matches_mount"])
            self.assertEqual(run.call_count, 2)

    def test_terminal_probe_uses_fixed_command_and_closes_session_after_sanitized_result(self):
        identifier = "a" * 64
        client = smoke.GuestClient()
        client.cookie = "titan_session=private-session"
        client.request = Mock(side_effect=[{"id": identifier}, {"ok": True}, {"ok": True}])
        payload = b"\nTITAN_SMOKE_DIAGNOSTIC:" + json.dumps({"available": True, "http_status": 200,
            "content_type": "text/html", "curl_category": "http_response", "private-key": "private-token"}).encode() + b"\r\n"
        response = Mock(status=200)
        response.readline.return_value = b'data: ' + json.dumps({"data": base64.b64encode(payload).decode()}).encode() + b'\n'
        with patch.object(smoke.http.client, "HTTPSConnection") as connection:
            connection.return_value.getresponse.return_value = response
            value = client.guest_diagnostic()
        self.assertEqual(value["http_status"], 200)
        self.assertNotIn("private", json.dumps(value))
        self.assertNotIn(identifier, json.dumps(value))
        sent = base64.b64decode(client.request.call_args_list[1].args[1]["data"]).decode()
        self.assertTrue(sent.startswith("python3 -c "))
        self.assertIn("http://127.0.0.1:18080/", sent)
        self.assertNotIn("private-session", sent)
        client.request.assert_any_call("/api/terminal", {"action": "close", "id": identifier})
        connection.return_value.close.assert_called_once()

    def test_terminal_probe_closes_session_even_when_stream_transport_fails(self):
        identifier = "b" * 64
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{"id": identifier}, {"ok": True}, {"ok": True}])
        with patch.object(smoke.http.client, "HTTPSConnection") as connection:
            connection.return_value.getresponse.side_effect = TimeoutError("private-error")
            self.assertEqual(client.guest_diagnostic(), {"available": False})
        client.request.assert_any_call("/api/terminal", {"action": "close", "id": identifier})

    def test_terminal_probe_does_not_accept_echoed_command_or_unbounded_output(self):
        identifier = "c" * 64
        client = smoke.GuestClient()
        client.request = Mock(side_effect=[{"id": identifier}, {"ok": True}, {"ok": True}])
        response = Mock(status=200)
        response.readline.side_effect = [b'data: '+json.dumps({"data": base64.b64encode(b'print("TITAN_SMOKE_DIAGNOSTIC:"+json.dumps(private))\n').decode()}).encode()+b'\n', b'']
        with patch.object(smoke.http.client, "HTTPSConnection") as connection:
            connection.return_value.getresponse.return_value = response
            self.assertEqual(client.guest_diagnostic(), {"available": False})

    def test_runtime_failure_report_preserves_sanitized_observations(self):
        client = FakeGuest()
        client.app_http_ready = Mock(side_effect=smoke.SmokeFailure("HTTP readiness failed.",
            {"last_http_status": 503, "last_transport": "http_response"}))
        stream = io.StringIO()
        with patch.object(smoke.time, "sleep"), contextlib.redirect_stdout(stream):
            report = smoke.RuntimeSmoke(client).run()
        check = next(item for item in report["checks"] if item["name"] == "docker_app_lifecycle")
        self.assertEqual(check["status"], "failed")
        self.assertEqual(check["values"], {"last_http_status": 503, "last_transport": "http_response"})
        line = next(line for line in stream.getvalue().splitlines() if line.startswith("TITAN_RUNTIME_FAILURE:"))
        self.assertEqual(json.loads(line.partition(":")[2]), check)

    def test_http_wait_retries_until_app_is_ready(self):
        first, ready = Mock(status=503), Mock(status=200)
        first.read.return_value, ready.read.return_value = b"starting", b"<title>Heimdall</title>"
        first.getheader.return_value = ready.getheader.return_value = "text/html"
        with patch.object(smoke.http.client, "HTTPConnection") as connection, patch.object(smoke.time, "sleep"):
            connection.return_value.getresponse.side_effect = [first, ready]
            self.assertTrue(smoke.GuestClient().app_http_ready()["app_page"])
            self.assertEqual(connection.call_count, 2)

    def test_console_pages_and_real_novnc_module_require_successful_delivery(self):
        responses = []
        for data in (b'<script src="/console.js">', b"import RFB from '/novnc/core/rfb.js'", b"class RFB {}"):
            response = Mock(status=200)
            response.read.return_value = data
            responses.append(response)
        client = smoke.GuestClient()
        client.cookie = "titan_session=private-fixture"
        with patch.object(smoke.http.client, "HTTPSConnection") as connection:
            connection.return_value.getresponse.side_effect = responses
            self.assertEqual(client.console_assets(), {"console_http": True, "novnc_assets": True})
        self.assertEqual([call.args[1] for call in connection.return_value.request.call_args_list],
                         ["/console.html", "/console.js", "/novnc/core/rfb.js"])
        for call in connection.return_value.request.call_args_list:
            self.assertEqual(call.kwargs["headers"]["Cookie"], client.cookie)

    def test_missing_novnc_asset_fails_without_response_publication(self):
        response = Mock(status=404)
        response.read.return_value = b"private-file-error"
        with patch.object(smoke.http.client, "HTTPSConnection") as connection:
            connection.return_value.getresponse.return_value = response
            with self.assertRaisesRegex(smoke.SmokeFailure, "assets are unavailable") as caught:
                smoke.GuestClient().console_assets()
        self.assertNotIn("private", str(caught.exception))

    def websocket_client(self, incoming, accept=None):
        key = base64.b64encode(bytes(16)).decode()
        digest = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        headers = ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: keep-alive, Upgrade\r\n"
                   f"Sec-WebSocket-Accept: {accept or digest}\r\nSec-WebSocket-Protocol: binary\r\n\r\n").encode()
        transport = MemoryTransport(headers + incoming)
        client = smoke.GuestClient()
        client.cookie = "titan_session=private-fixture"
        client.context = Mock()
        client.context.wrap_socket.return_value = transport
        return client, transport

    def test_authenticated_tls_upgrade_and_complete_rfb_initialization(self):
        client, transport = self.websocket_client(server_frame(rfb_fixture()))
        with patch.object(smoke.socket, "create_connection") as connect, patch.object(smoke.secrets, "token_bytes", side_effect=lambda size: bytes(size)):
            result = client.console_rfb("fixture-vm")
        connect.assert_called_once_with(("127.0.0.1", 15000), timeout=10)
        self.assertTrue(result["authenticated_websocket"])
        self.assertEqual((result["display_width"], result["display_height"]), (640, 480))
        request = transport.sent[0].decode()
        self.assertIn("GET /api/vnc?vm=fixture-vm HTTP/1.1", request)
        self.assertIn("Origin: https://10.0.2.15\r\n", request)
        self.assertIn("Cookie: titan_session=private-fixture", request)
        self.assertEqual([client_frame_payload(frame) for frame in transport.sent[1:]], [b"RFB 003.008\n", b"\x01", b"\x01"])
        self.assertNotIn("private-fixture", json.dumps(result))

    def test_invalid_websocket_accept_and_anonymous_console_do_not_pass(self):
        client, _ = self.websocket_client(server_frame(rfb_fixture()), accept="private-wrong-accept")
        with patch.object(smoke.socket, "create_connection"), patch.object(smoke.secrets, "token_bytes", side_effect=lambda size: bytes(size)):
            with self.assertRaisesRegex(smoke.SmokeFailure, "upgrade failed") as caught:
                client.console_rfb("fixture-vm")
        self.assertNotIn("private", str(caught.exception))
        client.cookie = ""
        with self.assertRaisesRegex(smoke.SmokeFailure, "authenticated"):
            client.console_rfb("fixture-vm")

    def test_console_reports_bounded_known_proxy_failure_without_leaking_response(self):
        for error, expected in (("VNC-Proxy ist nicht erreichbar.", "proxy startup timed out"),
                                ("private-response-body", "HTTP 400")):
            body = json.dumps({"error": error}).encode()
            transport = MemoryTransport(("HTTP/1.1 400 Bad Request\r\nContent-Length: " + str(len(body)) + "\r\n\r\n").encode() + body)
            client = smoke.GuestClient()
            client.cookie = "titan_session=private-fixture"
            client.context = Mock()
            client.context.wrap_socket.return_value = transport
            with patch.object(smoke.socket, "create_connection"):
                with self.assertRaisesRegex(smoke.SmokeFailure, expected) as caught:
                    client.console_rfb("fixture-vm")
            self.assertNotIn("private", str(caught.exception))

    def test_fragmented_binary_stream_and_ping_do_not_break_rfb(self):
        data = rfb_fixture()
        incoming = server_frame(b"ping", opcode=9) + server_frame(data[:8], final=False) + server_frame(data[8:], opcode=0)
        transport = MemoryTransport(incoming)
        result = smoke.VNCWebSocket(transport, smoke.time.monotonic() + 30).handshake()
        self.assertEqual(result["rfb_protocol"], "3.8")
        self.assertEqual(transport.sent[0][0], 0x8A)
        self.assertEqual(client_frame_payload(transport.sent[0]), b"ping")

    def test_unsupported_rfb_auth_and_wrong_protocol_are_failures(self):
        for data, detail in ((b"RFB 003.003\n", "expected RFB"), (b"RFB 003.008\n\x01\x02", "unsupported RFB authentication")):
            transport = MemoryTransport(server_frame(data))
            with self.assertRaisesRegex(smoke.SmokeFailure, detail):
                smoke.VNCWebSocket(transport, smoke.time.monotonic() + 30).handshake()

    def test_oversized_frames_and_ping_flood_are_bounded(self):
        for data, detail in ((b"\x82\x7f" + struct.pack("!Q", 1024 * 1024 + 1), "frame size"),
                             (server_frame(b"", opcode=9) * 129, "frame count")):
            with self.assertRaisesRegex(smoke.SmokeFailure, detail):
                smoke.VNCWebSocket(MemoryTransport(data), smoke.time.monotonic() + 30).handshake()

    def test_console_deadline_and_invalid_display_metadata_fail(self):
        with patch.object(smoke.time, "monotonic", return_value=31):
            with self.assertRaisesRegex(smoke.SmokeFailure, "deadline"):
                smoke.VNCWebSocket(MemoryTransport(b""), 30).handshake()
        data = bytearray(rfb_fixture())
        data[18:22] = bytes(4)  # ServerInit zero width and height.
        with self.assertRaisesRegex(smoke.SmokeFailure, "display metadata"):
            smoke.VNCWebSocket(MemoryTransport(server_frame(data)), smoke.time.monotonic() + 30).handshake()

    def test_qemu_app_forward_is_fixed_loopback_in_disposable_overlay(self):
        source = (Path(__file__).resolve().parents[1] / "scripts/smoke-image.sh").read_text()
        self.assertIn("hostfwd=tcp:127.0.0.1:15080-:18080", source)
        self.assertIn("hostfwd=tcp:127.0.0.1:15000-:443", source)
        self.assertIn("hostfwd=tcp:127.0.0.1:15001-:5000", source)
        self.assertIn("hostfwd=tcp:127.0.0.1:15081-:80", source)
        self.assertIn('file="$task_dir/test.qcow2"', source)


class PersistentLoginGuest:
    """Exercise the smoke procedure against the real persistent SQLite policy."""
    def __init__(self, directory):
        from titan.core import Store
        from titan.login_protection import LoginProtection
        self.directory = directory
        self.store = Store(directory)
        self.store.create_user('admin', 'admin-password-long', 'admin', 'admin')
        self.protection = LoginProtection(self.store)
        self.credentials = []
        self.drop_retry = False
        self.erase_second_client_block = False
        self.client_count = 0
        self.fail_cleanup = False

    def request(self, path, body=None):
        if path == '/api/security/login-protection':
            return self.protection.overview('admin') if body is None else self.protection.save('admin', body['settings'], body['expected_revision'])
        if path == '/api/security/login-protection/unblock':
            return self.protection.unblock('admin', body['id'])
        if path == '/api/users': return {'web': self.store.users()}
        raise AssertionError('Unexpected persistent login fixture route.')

    def user_create(self, name, password):
        self.credentials.append(password)
        self.store.create_user(name, password, 'user', name)
        return {'ok': True}

    def user_remove(self, name):
        from titan.users import Users
        if self.fail_cleanup: raise RuntimeError('private-cleanup-diagnostic')
        return Users(self.store, Mock()).remove('admin', name, name)

    def unauthenticated_client(self):
        from titan.core import Store
        guest = self
        self.client_count += 1
        store = Store(self.directory)
        if self.erase_second_client_block and self.client_count == 2:
            with store.connection() as db: db.execute('DELETE FROM login_protection_blocks')
        class Anonymous:
            cookie = ''
            last_retry_after = 0
            def request(self, path, body, expected_status=None):
                from titan.core import Error
                if path != '/api/login': raise AssertionError('Unexpected anonymous test route.')
                status = 200
                try:
                    token, csrf = store.login(body['name'], body['password'], address='192.0.2.11')
                    self.cookie = 'titan_session=' + token
                    result = {'ok': True, 'csrf': csrf}
                except Error as error:
                    status = error.status
                    result = {'error': str(error)}
                    if hasattr(error, 'retry_after'):
                        result['retry_after'] = error.retry_after
                        self.last_retry_after = 0 if guest.drop_retry else error.retry_after
                if status != (expected_status or 200):
                    raise smoke.SmokeFailure('Persistent login fixture observed an unexpected authentication status.')
                return result
        return Anonymous()


class LoginProtectionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.guest = PersistentLoginGuest(self.temp.name)
        self.original = self.guest.request('/api/security/login-protection')['settings']

    def tearDown(self): self.temp.cleanup()

    def assert_cleanup(self):
        self.assertEqual(self.guest.request('/api/security/login-protection')['settings'], self.original)
        self.assertEqual([item['name'] for item in self.guest.store.users()], ['admin'])
        self.assertEqual(self.guest.request('/api/security/login-protection')['blocks'], [])

    def test_actual_persistent_threshold_unblock_and_safe_cleanup(self):
        result = smoke.RuntimeSmoke(self.guest).login_protection()
        self.assertTrue(all(value is True for value in result.values()))
        self.assertEqual(self.guest.client_count, 2)
        self.assertNotIn(self.guest.credentials[0], json.dumps(result))
        self.assert_cleanup()

    def test_missing_retry_header_fails_and_still_restores_policy_and_user(self):
        self.guest.drop_retry = True
        with self.assertRaises(smoke.SmokeFailure) as error: smoke.RuntimeSmoke(self.guest).login_protection()
        self.assertIn('Retry-After', str(error.exception))
        self.assert_cleanup()

    def test_lost_persistent_block_fails_and_still_cleans_up(self):
        self.guest.erase_second_client_block = True
        with self.assertRaises(smoke.SmokeFailure): smoke.RuntimeSmoke(self.guest).login_protection()
        self.assert_cleanup()

    def test_cleanup_failure_fails_gate_without_publishing_raw_exception(self):
        self.guest.fail_cleanup = True
        runner = smoke.RuntimeSmoke(self.guest)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(runner.run_check('login_protection', runner.login_protection))
        rendered = json.dumps(runner.report) + output.getvalue()
        self.assertNotIn('private-cleanup-diagnostic', rendered)
        self.assertNotIn(self.guest.credentials[0], rendered)
        self.assertIn('restore its policy or remove', rendered)


if __name__ == "__main__":
    unittest.main()

class RegistryThrottleRetryTests(unittest.TestCase):
    def test_throttled_install_resumes_start_without_recreating_app(self):
        guest=Mock();guest.action.side_effect=[smoke.SmokeFailure('throttled', {'error_category':'registry_rate_limit'}), {'ok':True}]
        runtime=smoke.RuntimeSmoke(guest)
        with patch.object(smoke.time,'sleep') as sleep:
            self.assertEqual(runtime.install_test_app({'app':'heimdall','port':18080,'network':{'mode':'bridge','name':'test'}}), {'ok':True})
        self.assertEqual(guest.action.call_args_list[0].args[0],'app_install')
        self.assertEqual(guest.action.call_args_list[1].args,('app_action',{'app':'heimdall','action':'start'}))
        sleep.assert_called_once_with(30)

    def test_persistent_throttle_still_fails_release_gate(self):
        guest=Mock();guest.action.side_effect=smoke.SmokeFailure('throttled', {'error_category':'registry_rate_limit'})
        with patch.object(smoke.time,'sleep') as sleep,self.assertRaises(smoke.SmokeFailure):
            smoke.RuntimeSmoke(guest).install_test_app({'app':'heimdall','port':18080})
        self.assertEqual(guest.action.call_count,4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[30,60,120])

    def test_other_failures_never_retry(self):
        for category in ('registry_auth','container_runtime','unknown'):
            with self.subTest(category=category):
                guest=Mock();guest.action.side_effect=smoke.SmokeFailure('failed', {'error_category':category})
                with patch.object(smoke.time,'sleep') as sleep,self.assertRaises(smoke.SmokeFailure):
                    smoke.RuntimeSmoke(guest).install_test_app({'app':'heimdall','port':18080})
                guest.action.assert_called_once();sleep.assert_not_called()


class StorageBoundaryGuest:
    """Exercise the smoke through real file operations in a private root fixture."""
    def __init__(self, root):
        from titan import system_files
        self.module = system_files
        self.root = root
        (root/'var/srv/titan').mkdir(parents=True)
        (root/'etc').mkdir()
        (root/'etc/hostname').write_text('private-fixture-host\n')
        self.fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.resource = {'id':'system','kind':'internal','path':'/var/srv/titan','label':'Interner Speicher',
            'available':True,'status':'ready','capabilities':['apps','files','shares','vms'],
            'total_bytes':1000000,'free_bytes':500000}
        self.default_path = 'var/srv/titan'
        self.fail_cleanup = False
        self.bypass_os = False
        self.bypass_write_guard = False

    def request(self, url, body=None, expected_status=None):
        from titan.core import Error
        parsed=urlsplit(url)
        if parsed.path=='/api/storage-locations':
            return {'storage':[copy.deepcopy(self.resource)],'default_storage':'system'}
        assert parsed.path=='/api/files'
        if body is None:
            query={key:value[0] for key,value in parse_qs(parsed.query,keep_blank_values=True).items()}
            action='list';path=query['path'] or self.default_path
            arguments={key:value for key,value in query.items() if key not in ('path','share')}
        else:
            action=body['action'];path=body['path']
            arguments={key:value for key,value in body.items() if key not in ('action','path','share')}
        if self.fail_cleanup and action=='delete':
            raise RuntimeError('private-guest-credential')
        status=200
        try:
            if self.bypass_os or self.bypass_write_guard and path=='etc/hostname' and action=='write':
                from titan.files import operate
                value=operate(self.fd,action,path,**arguments)
            else:
                value=self.module.operate_system(self.fd,action,path,system_path_root=str(self.root),
                    allowed_roots=['var/srv/titan'],**arguments)
        except Error as error:
            status=error.status;value={'error':str(error)}
        if (expected_status is not None and status!=expected_status or
                expected_status is None and not 200<=status<300):
            raise smoke.SmokeFailure('Test API returned HTTP '+str(status)+'.')
        return value


class StorageBoundarySmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.guest=StorageBoundaryGuest(Path(self.temp.name))
        self.addCleanup(os.close,self.guest.fd)

    def test_real_nas_file_create_edit_revision_and_delete_with_os_denial(self):
        values=smoke.RuntimeSmoke(self.guest).storage_data_boundary()
        self.assertTrue(all(value is True for value in values.values()))
        self.assertEqual(list((self.guest.root/'var/srv/titan').iterdir()),[])
        self.assertEqual((self.guest.root/'etc/hostname').read_text(),'private-fixture-host\n')
        self.assertNotIn('private-fixture-host',json.dumps(values))

    def test_missing_or_unready_named_resource_fails_without_creating_files(self):
        for field,value in [('available',False),('capabilities',['files','backups']),
                            ('free_bytes',True),('path','/'),('status','offline')]:
            with self.subTest(field=field):
                original=self.guest.resource[field];self.guest.resource[field]=value
                with self.assertRaises(smoke.SmokeFailure):smoke.RuntimeSmoke(self.guest).storage_data_boundary()
                self.guest.resource[field]=original
        self.assertEqual(list((self.guest.root/'var/srv/titan').iterdir()),[])

    def test_default_browser_must_report_the_nas_root(self):
        self.guest.default_path='var/srv/titan/subfolder'
        (self.guest.root/self.guest.default_path).mkdir()
        with self.assertRaisesRegex(smoke.SmokeFailure,'Default file browser'):
            smoke.RuntimeSmoke(self.guest).storage_data_boundary()

    def test_os_read_bypass_blocks_runtime_evidence(self):
        self.guest.bypass_os=True
        with self.assertRaises(smoke.SmokeFailure):smoke.RuntimeSmoke(self.guest).storage_data_boundary()
        self.assertEqual(list((self.guest.root/'var/srv/titan').iterdir()),[])

    def test_missing_write_scope_guard_fails_safely_without_changing_hostname(self):
        self.guest.bypass_write_guard=True
        with self.assertRaises(smoke.SmokeFailure):smoke.RuntimeSmoke(self.guest).storage_data_boundary()
        self.assertEqual((self.guest.root/'etc/hostname').read_text(),'private-fixture-host\n')

    def test_failed_cleanup_blocks_evidence_and_redacts_exception(self):
        self.guest.fail_cleanup=True
        runner=smoke.RuntimeSmoke(self.guest)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(runner.run_check('storage_data_boundary',runner.storage_data_boundary))
        rendered=json.dumps(runner.report)
        self.assertIn('could not remove its test-owned file',rendered)
        self.assertNotIn('private-guest-credential',rendered)


class ContainmentGuest:
    """API proof fixture only; never execute or create a host systemd service."""
    name = 'titan-custom-smoke-a1b2c3d4.service'

    def __init__(self):
        self.evidence={'verified':True,'units':[{'name':self.name,'was_enabled':True,'was_running':True}]}
        self.service={'name':self.name,'active':'inactive','enabled':False,'unit_file_state':'disabled',
            'protected_reason':'Älterer eigener Rootdienst deaktiviert',
            'allowed_actions':['stop','disable','reset-failed'],
            'properties':{'LoadState':'loaded','User':'root','MainPID':'0',
                'FragmentPath':'/etc/systemd/system/'+self.name}}
        self.gate={'active':'active','properties':{'Result':'success','DefaultDependencies':'no',
            'Before':'basic.target titan-agent.service','After':'local-fs.target'}}
        self.agent={'properties':{'After':'titan-service-containment.service',
            'Requires':'titan-service-containment.service'}}
        self.accept_root=False
        self.actions=[]

    def request(self,path,body=None):
        if path=='/api/services':return {'root_containment':copy.deepcopy(self.evidence),'items':[copy.deepcopy(self.service)]}
        if path.startswith('/api/service-details?'):
            name=parse_qs(urlsplit(path).query)['service'][0]
            value=self.gate if name=='titan-service-containment.service' else self.agent if name=='titan-agent.service' else self.service
            return {'service':copy.deepcopy(value)}
        if path=='/api/actions':
            assert body['operation']=='service_action' and body['arguments']['service']==self.name
            self.actions.append(body['arguments']['command'])
            return {'job':'owned-job'}
        if path=='/api/jobs':
            return [{'id':'owned-job','status':'completed' if self.accept_root else 'failed',
                'result':{'ok':True} if self.accept_root else {'error':'Dieser ältere eigene Dienst benötigt ein Datenbenutzerkonto. root-Dienste können hier nur angehalten oder deaktiviert werden.'}}]
        raise AssertionError(path)


class CustomServiceContainmentSmokeTests(unittest.TestCase):
    def setUp(self):
        self.guest=ContainmentGuest()

    def prove(self):
        return smoke.RuntimeSmoke(self.guest,self.guest.name).custom_service_containment()

    def test_running_enabled_root_is_verified_stopped_disabled_preserved_and_api_denied(self):
        values=self.prove()
        self.assertTrue(all(value is True for value in values.values()))
        self.assertEqual(self.guest.actions,['start','enable'])
        self.assertNotIn(self.guest.name,json.dumps(values))

    def test_missing_or_untrusted_fixture_cannot_produce_success_evidence(self):
        for name in (None,'sshd.service','titan-custom-normal.service','titan-custom-smoke-*.service'):
            with self.subTest(name=name), self.assertRaises(smoke.SmokeFailure):
                smoke.RuntimeSmoke(self.guest,name).custom_service_containment()
        self.assertEqual(self.guest.actions,[])

    def test_fixture_must_have_been_running_and_enabled_before_actual_boot_helper(self):
        for field,value in (('verified',False),('was_running',False),('was_enabled',False)):
            with self.subTest(field=field):
                self.guest=ContainmentGuest()
                if field=='verified':self.guest.evidence[field]=value
                else:self.guest.evidence['units'][0][field]=value
                with self.assertRaises(smoke.SmokeFailure):self.prove()

    def test_running_enabled_missing_file_or_startable_legacy_service_blocks_evidence(self):
        for field,value in (('active','active'),('enabled',True),('unit_file_state','enabled'),
                ('allowed_actions',['start']),('protected_reason','')):
            with self.subTest(field=field):
                self.guest=ContainmentGuest();self.guest.service[field]=value
                with self.assertRaises(smoke.SmokeFailure):self.prove()
        for field,value in (('LoadState','not-found'),('MainPID','42'),('FragmentPath','/usr/lib/systemd/system/foreign.service')):
            with self.subTest(field=field):
                self.guest=ContainmentGuest();self.guest.service['properties'][field]=value
                with self.assertRaises(smoke.SmokeFailure):self.prove()

    def test_failed_or_late_gate_or_ungated_management_cannot_pass(self):
        for field,value in (('Result','exit-code'),('DefaultDependencies','yes'),('Before',''),('After','')):
            with self.subTest(field=field):
                self.guest=ContainmentGuest();self.guest.gate['properties'][field]=value
                with self.assertRaises(smoke.SmokeFailure):self.prove()
        for field in ('Requires','After'):
            with self.subTest(field=field):
                self.guest=ContainmentGuest();self.guest.agent['properties'][field]=''
                with self.assertRaises(smoke.SmokeFailure):self.prove()

    def test_api_accepting_root_start_is_a_real_runtime_failure(self):
        self.guest.accept_root=True
        with self.assertRaisesRegex(smoke.SmokeFailure,'did not reject'):self.prove()
