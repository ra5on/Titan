import copy
import ipaddress
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_app_management as fixtures
from titan.app_networks import selection, validate_create
from titan.catalog import APPS, compose, published_ports
from titan.core import Error
from titan.demo import Demo


class AppNetworkTests(unittest.TestCase):
    def setUp(self):
        self.networks = {"bridge": self.network("bridge", "172.17.0.0/16", "172.17.0.1")}
        self.routes = [{"dst": "192.168.1.0/24", "dev": "eth0"}, {"dst": "default"}]
        self.listeners = ""
        self.created_sequence = 100
        fixtures.AppManagementTests.setUp(self)

    tearDown = fixtures.AppManagementTests.tearDown

    @staticmethod
    def network(name, subnet, gateway, internal=False, driver="bridge", managed=False):
        return {"Id": (name.encode().hex() + "0" * 64)[:64], "Name": name, "Driver": driver, "Scope": "local", "Internal": internal,
                "IPAM": {"Config": [{"Subnet": subnet, "Gateway": gateway}]}, "Containers": {},
                "Labels": {"io.titan.managed": "true", "io.titan.network": name} if managed else {}}

    def command(self, arguments, **kwargs):
        if arguments[:2] == ["docker", "network"]:
            self.calls.append(arguments)
            action = arguments[2]
            if action == "ls":
                return "\n".join(item["Id"] for item in self.networks.values())
            if action == "inspect":
                results = []
                for name in arguments[3:]:
                    item = next((item for key, item in self.networks.items() if name in (key, item["Id"])), None)
                    if item is None:
                        raise Error("network not found", 404)
                    result = copy.deepcopy(item)
                    for app, container in self.containers.items():
                        attached = container.get("NetworkSettings", {}).get("Networks", {}).get(item["Name"])
                        if attached and container["State"]["Status"] == "running":
                            result["Containers"][container["Id"]] = {"Name": "titan-" + app, "IPv4Address": attached["IPAddress"] + "/24", "IPv6Address": attached.get("GlobalIPv6Address", "")}
                    results.append(result)
                return json.dumps(results)
            if action == "create":
                name = arguments[-1]
                item = self.network(name, arguments[arguments.index("--subnet") + 1], arguments[arguments.index("--gateway") + 1], "--internal" in arguments, managed=True)
                self.networks[name] = item
                return item["Id"]
            if action == "rm":
                key = next(name for name, item in self.networks.items() if item["Id"] == arguments[-1])
                del self.networks[key]
                return arguments[-1]
        if arguments[:4] == ["ip", "-j", "-4", "route"]:
            self.calls.append(arguments)
            return json.dumps(self.routes)
        if arguments[:3] == ["ip", "-j", "address"]:
            self.calls.append(arguments)
            return json.dumps([{"ifname": "eth0", "addr_info": [{"family": "inet", "local": "192.168.1.50"}, {"family": "inet6", "local": "fd00::50"}]},
                               {"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1"}]},
                               {"ifname": "docker0", "addr_info": [{"family": "inet", "local": "172.17.0.1"}]}])
        if arguments[:1] == ["ss"]:
            self.calls.append(arguments)
            return self.listeners
        result = fixtures.AppManagementTests.command(self, arguments, **kwargs)
        if arguments[:2] == ["docker", "compose"] and "-f" in arguments and arguments[6] in ("start", "restart"):
            app = arguments[3][6:]
            self.containers[app]["State"].update(StartedAt="2026-10-02T06:00:00Z", Running=True)
            for name, endpoint in self.containers[app]["NetworkSettings"]["Networks"].items():
                if name != "host":
                    subnet = self.networks[name]["IPAM"]["Config"][0]["Subnet"]
                    endpoint["NetworkID"] = self.networks[name]["Id"]
                    endpoint["EndpointID"] = "e" * 64
                    endpoint["IPAddress"] = (endpoint.get("IPAMConfig") or {}).get("IPv4Address") or str(ipaddress.IPv4Network(subnet).network_address + 10)
                    endpoint["GlobalIPv6Address"] = "fd00:22::10"
        return result

    def make_container(self, app="jellyfin", state="running"):
        self.label_sequence += 1
        record = next(item for item in self.host.load("apps", []) if item["id"] == app)
        service = compose(app, str(self.host.directory / "apps" / app), self.owner.pw_uid, self.owner.pw_gid,
                          record["port"], record["data"], self.host._app_options(app), record.get("network"))["services"][app]
        publications = published_ports(app, record["port"], self.host._app_options(app), host_mode=selection(record.get("network"))["mode"] == "host")
        bindings = {f"{item['target']}/{item['protocol']}": [{"HostIp": "", "HostPort": str(item["host"])}] for item in publications} if "ports" in service else {}
        network = selection(record.get("network"))
        name = network.get("name", "bridge") if network["mode"] == "bridge" else "titan-" + app + "_default"
        if network["mode"] == "host": name = "host"
        if name not in self.networks:
            self.networks[name] = self.network(name, "172.22.0.0/24", "172.22.0.1", driver="host" if name == "host" else "bridge")
        info = self.networks[name]
        requested = network.get("ipv4_address")
        address = requested or str(ipaddress.IPv4Network(info["IPAM"]["Config"][0]["Subnet"]).network_address + 10)
        item = {"Id": (app.encode().hex() + "a" * 64)[:64], "Name": "/titan-" + app,
                "MountLabel": f"system_u:object_r:container_file_t:s0:c10,c{20+self.label_sequence}",
                "Config": {"Image": service["image"], "Env": ["SECRET=hidden"], "Labels": {**service["labels"], "com.docker.compose.project": "titan-" + app, "com.docker.compose.service": app}},
                "Mounts": [{"Type": "bind", "Source": binding["source"], "Destination": binding["target"]} for binding in service["volumes"]],
                "HostConfig": {"Privileged": False, "NetworkMode": name, "PortBindings": bindings},
                "State": {"Status": state, "ExitCode": 0, "Error": "", "Running": state == "running",
                          "StartedAt": "0001-01-01T00:00:00Z" if state == "created" else "2026-10-02T06:00:00Z"}, "RestartCount": 0,
                "NetworkSettings": {"Ports": {key: [{"HostIp": "0.0.0.0", "HostPort": item["HostPort"]} for item in values] for key, values in bindings.items()},
                    "Networks": {name: {"NetworkID": "" if state == "created" else info["Id"],
                        "EndpointID": "" if state == "created" else "e" * 64,
                        "IPAMConfig": {"IPv4Address": requested} if requested else None,
                        "IPAddress": address if state == "running" and name != "host" else "", "Gateway": info["IPAM"]["Config"][0]["Gateway"] if name != "host" else "",
                        "GlobalIPv6Address": "fd00:22::10" if name != "host" and state == "running" else "", "IPv6Gateway": "fd00:22::1" if name != "host" else ""}}}}
        self.containers[app] = item
        return item

    def create(self, name="titan-test", subnet="172.30.241.0/24", internal=False):
        return self.host.op_app_network_create(name, subnet, internal=internal)

    def install(self, app="heimdall", port=18080, address="172.30.241.10"):
        self.create()
        self.host.op_app_install(app, port, network={"mode": "bridge", "name": "titan-test", "ipv4_address": address})

    def test_create_inspects_actual_network_and_stores_configuration(self):
        result = self.create(internal=True)
        self.assertTrue(result["network"]["managed"])
        self.assertTrue(result["network"]["internal"])
        self.assertEqual(result["network"]["subnets"], [{"subnet": "172.30.241.0/24", "gateway": "172.30.241.1", "family": 4}])
        self.assertEqual(self.host.load("app-networks", [])[0]["id"], self.networks["titan-test"]["Id"])
        self.assertTrue(any(command[:3] == ["docker", "network", "inspect"] for command in self.calls))

    def test_network_inventory_uses_actual_driver_addresses_and_no_secrets(self):
        self.install()
        inventory = self.host.op_app_networks()
        value = next(item for item in inventory["networks"] if item["name"] == "titan-test")
        self.assertTrue(value["managed"])
        self.assertEqual(value["used_by"], ["heimdall"])
        self.assertEqual(value["containers"][0]["ipv4"], "172.30.241.10")
        self.assertEqual(len(inventory["host_addresses"]), 3)
        self.assertNotIn("172.17.0.1", json.dumps(inventory["host_addresses"]))
        self.assertIsNone(inventory["public_ip"])

    def test_static_ip_persists_compose_restarts_updates_backups(self):
        self.install()
        compose_path = self.host.directory / "apps/heimdall/compose.json"
        before = compose_path.read_bytes()
        self.assertEqual(json.loads(before)["networks"], {"selected": {"external": True, "name": "titan-test"}})
        for action in ("stop", "start", "restart", "backup", "update"):
            self.host.op_app_action("heimdall", action)
        self.assertEqual(compose_path.read_bytes(), before)
        record = self.host.load("apps", [])[0]
        self.assertEqual(record["network"]["ipv4_address"], "172.30.241.10")
        self.assertEqual(self.host.op_app_details("heimdall")["container"]["networks"][0]["ipv4"], "172.30.241.10")

    def test_created_bridge_without_allocated_network_id_passes_pre_start_inspection(self):
        inspected = []
        def inspect_before_start(app, record):
            container = self.containers[app]
            endpoint = container["NetworkSettings"]["Networks"]["titan-test"]
            self.assertEqual(container["State"]["Status"], "created")
            self.assertEqual(endpoint["NetworkID"], "")
            self.assertEqual(endpoint["IPAMConfig"]["IPv4Address"], "172.30.241.10")
            self.calls.clear()
            self.assertIsNotNone(self.host._app_container(app, record))
            self.assertIn(["docker", "network", "inspect", "titan-test"], self.calls)
            inspected.append(app)
        with patch.object(self.host, "_app_private_config_label", side_effect=inspect_before_start):
            self.install()
        self.assertEqual(inspected, ["heimdall"])
        endpoint = self.containers["heimdall"]["NetworkSettings"]["Networks"]["titan-test"]
        self.assertEqual(endpoint["NetworkID"], self.host.managed_app("heimdall")["network_id"])
        self.assertEqual(self.host.managed_app("heimdall")["phase"], "ready")

    def test_created_bridge_missing_id_rechecks_actual_selected_network(self):
        self.install()
        record = self.host.managed_app("heimdall")
        self.make_container("heimdall", "created")
        original = copy.deepcopy(self.networks["titan-test"])
        for change in ({"Id": "f" * 64}, {"Driver": "macvlan"}):
            with self.subTest(change=change):
                self.networks["titan-test"] = {**original, **change}
                with self.assertRaises(Error):
                    self.host._app_container("heimdall", record)
        del self.networks["titan-test"]
        with self.assertRaises(Error):
            self.host._app_container("heimdall", record)

    def test_missing_network_id_is_rejected_after_start_or_without_zero_timestamp(self):
        self.install()
        record = self.host.managed_app("heimdall")
        states = [{"Status": value} for value in ("running", "restarting", "exited", "dead", "paused")]
        states += [{"StartedAt": "2026-10-02T06:00:00Z"}, {"StartedAt": None},
                   {"Running": True}, {"Restarting": True}, {"Paused": True}]
        for change in states:
            with self.subTest(change=change):
                container = self.make_container("heimdall", "created")
                container["State"].update(change)
                with self.assertRaises(Error):
                    self.host._app_container("heimdall", record)
        for change in ({"NetworkID": "f" * 64}, {"NetworkID": None}, {"EndpointID": "e" * 64}):
            with self.subTest(endpoint=change):
                container = self.make_container("heimdall", "created")
                container["NetworkSettings"]["Networks"]["titan-test"].update(change)
                with self.assertRaises(Error):
                    self.host._app_container("heimdall", record)

    def test_details_show_observed_ipv4_ipv6_gateway_host_binding_and_lan_endpoint(self):
        self.install()
        details = self.host.op_app_details("heimdall")["container"]
        self.assertEqual(details["networks"][0], {"name": "titan-test", "driver": "bridge", "ipv4": "172.30.241.10", "ipv6": "fd00:22::10", "gateway": "172.30.241.1", "ipv6_gateway": "fd00:22::1", "internal": False})
        self.assertIn({"url": "http://192.168.1.50:18080", "address": "192.168.1.50", "port": 18080, "scope": "lan", "source": "published"}, details["endpoints"])
        self.assertEqual(details["ports"][0]["host"], "0.0.0.0")
        self.assertIsNone(details["public_ip"])
        self.assertNotIn("SECRET", json.dumps(details))
        self.assertEqual(self.host.op_apps()["installed"][0]["container"]["networks"], details["networks"])

    def test_stopped_container_has_no_reachable_endpoint_or_invented_static_ip(self):
        self.install()
        self.containers["heimdall"]["State"]["Status"] = "exited"
        self.containers["heimdall"]["NetworkSettings"]["Networks"]["titan-test"]["IPAddress"] = ""
        details = self.host.op_app_details("heimdall")["container"]
        self.assertEqual(details["networks"][0]["ipv4"], "")
        self.assertEqual(details["endpoints"], [])

    def test_changed_static_ip_network_id_or_attachment_blocks_operations(self):
        self.install()
        original = copy.deepcopy(self.containers["heimdall"])
        for changes in ({"IPAddress": "172.30.241.99"}, {"NetworkID": "f" * 64}, {"IPAMConfig": {"IPv4Address": "172.30.241.99"}}):
            self.containers["heimdall"] = copy.deepcopy(original)
            self.containers["heimdall"]["NetworkSettings"]["Networks"]["titan-test"].update(changes)
            with self.assertRaises(Error): self.host.op_app_action("heimdall", "restart")
        self.containers["heimdall"] = copy.deepcopy(original)
        self.containers["heimdall"]["NetworkSettings"]["Networks"]["foreign"] = {}
        with self.assertRaises(Error): self.host.op_app_action("heimdall", "restart")

    def test_external_bridge_accepts_pinned_id_as_engine_network_mode(self):
        self.install()
        record = self.host.managed_app("heimdall")
        container = self.containers["heimdall"]
        container["HostConfig"]["NetworkMode"] = record["network_id"]
        self.assertIsNotNone(self.host._app_container("heimdall", record))
        container["HostConfig"]["NetworkMode"] = "f" * 64
        with self.assertRaises(Error):
            self.host._app_container("heimdall", record)
        container["HostConfig"]["NetworkMode"] = record["network_id"]
        container["NetworkSettings"]["Networks"]["titan-test"]["NetworkID"] = "f" * 64
        with self.assertRaises(Error):
            self.host._app_container("heimdall", record)

    def test_replaced_network_blocks_start_even_when_container_missing(self):
        self.install()
        self.containers.clear()
        self.networks["titan-test"]["Id"] = "f" * 64
        with self.assertRaises(Error): self.host.op_app_action("heimdall", "start")

    def test_removed_network_blocks_start_before_compose(self):
        self.install()
        self.containers.clear()
        del self.networks["titan-test"]
        self.calls.clear()
        with self.assertRaises(Error): self.host.op_app_action("heimdall", "start")
        self.assertFalse(any(command[:2] == ["docker", "compose"] for command in self.calls))

    def test_network_create_rejects_docker_and_host_route_overlap(self):
        for subnet in ("172.17.1.0/24", "192.168.1.0/24"):
            with self.assertRaises(Error): self.create(subnet=subnet)
        self.assertFalse(any(command[:3] == ["docker", "network", "create"] for command in self.calls))

    def test_invalid_bridge_creation_never_calls_docker(self):
        invalid = [("foreign", "172.30.1.0/24", None, False), ("titan-test", "8.8.8.0/24", None, False),
                   ("titan-test", "172.30.1.1/24", None, False), ("titan-test", "172.30.1.0/31", None, False),
                   ("titan-test", "172.30.1.0/24", "172.31.1.1", False), ("titan-test", "172.30.1.0/24", "172.30.1.255", False),
                   ("titan-test", "172.30.1.0/24", None, "true"), ("titan-test;echo", "172.30.1.0/24", None, False)]
        for name, subnet, gateway, internal in invalid:
            with self.subTest(name=name, subnet=subnet, gateway=gateway, internal=internal):
                with self.assertRaises(Error): self.host.op_app_network_create(name, subnet, gateway, internal)
        self.assertEqual(self.calls, [])

    def test_gateway_network_broadcast_or_outside_static_address_rejected(self):
        self.create()
        for address in ("172.30.241.0", "172.30.241.1", "172.30.241.255", "172.31.0.10"):
            with self.subTest(address=address):
                with self.assertRaises(Error): self.host.op_app_install("heimdall", 18080, network={"mode": "bridge", "name": "titan-test", "ipv4_address": address})
        self.assertEqual(self.host.load("apps", []), [])

    def test_reserved_static_address_rejected_when_other_app_is_stopped(self):
        self.install()
        self.containers["heimdall"]["State"]["Status"] = "exited"
        with self.assertRaises(Error): self.host.op_app_install("grocy", 19283, network={"mode": "bridge", "name": "titan-test", "ipv4_address": "172.30.241.10"})

    def test_foreign_container_static_address_rejected(self):
        self.create()
        self.networks["titan-test"]["Containers"] = {"f" * 64: {"Name": "foreign", "IPv4Address": "172.30.241.10/24"}}
        with self.assertRaises(Error): self.host.op_app_install("heimdall", 18080, network={"mode": "bridge", "name": "titan-test", "ipv4_address": "172.30.241.10"})

    def test_ipam_reserved_auxiliary_address_rejected(self):
        self.create()
        self.networks["titan-test"]["IPAM"]["Config"][0]["AuxiliaryAddresses"] = {"reserved": "172.30.241.10"}
        with self.assertRaises(Error): self.host.op_app_install("heimdall", 18080, network={"mode": "bridge", "name": "titan-test", "ipv4_address": "172.30.241.10"})

    def test_builtin_bridge_supports_dynamic_ip_but_rejects_static_ip(self):
        self.host.op_app_install("heimdall", 18080, network={"mode": "bridge"})
        self.assertEqual(json.loads((self.host.directory / "apps/heimdall/compose.json").read_text())["services"]["heimdall"]["network_mode"], "bridge")
        with self.assertRaises(Error): self.host.op_app_install("grocy", 19283, network={"mode": "bridge", "name": "bridge", "ipv4_address": "172.17.0.11"})

    def test_other_network_drivers_are_not_deployable(self):
        self.networks["foreign"] = self.network("foreign", "172.31.0.0/24", "172.31.0.1", driver="macvlan")
        self.assertFalse(next(item for item in self.host.op_app_networks()["networks"] if item["name"] == "foreign")["selectable"])
        with self.assertRaises(Error): self.host.op_app_install("heimdall", 18080, network={"mode": "bridge", "name": "foreign"})

    def test_remove_requires_exact_name_owned_id_unused_and_preserves_foreign(self):
        self.create()
        with self.assertRaises(Error): self.host.op_app_network_remove("titan-test", "other")
        with self.assertRaises(Error): self.host.op_app_network_remove("bridge", "bridge")
        self.assertTrue(self.host.op_app_network_remove("titan-test", "titan-test")["ok"])
        self.assertNotIn("titan-test", self.networks)
        self.assertIn("bridge", self.networks)
        self.assertEqual(self.host.load("app-networks", []), [])

    def test_remove_blocks_installed_app_even_when_stopped_and_unattached(self):
        self.install()
        self.containers.clear()
        with self.assertRaises(Error): self.host.op_app_network_remove("titan-test", "titan-test")
        self.host.op_app_action("heimdall", "remove")
        self.host.op_app_network_remove("titan-test", "titan-test")
        self.assertNotIn("titan-test", self.networks)

    def test_remove_blocks_forged_managed_label_or_replaced_id(self):
        self.create()
        self.networks["titan-test"]["Id"] = "f" * 64
        with self.assertRaises(Error): self.host.op_app_network_remove("titan-test", "titan-test")

    def test_host_mode_uses_actual_internal_port_without_published_ports(self):
        self.host.op_app_install("heimdall", 80, network={"mode": "host"})
        value = json.loads((self.host.directory / "apps/heimdall/compose.json").read_text())["services"]["heimdall"]
        self.assertNotIn("ports", value)
        self.assertEqual(value["network_mode"], "host")
        details = self.host.op_app_details("heimdall")["container"]
        self.assertEqual(details["ports"], [])
        self.assertEqual(details["networks"][0]["ipv4"], "")
        self.assertIn("http://192.168.1.50:80", [item["url"] for item in details["endpoints"]])

    def test_host_mode_rejects_remapping_and_conflicting_local_service(self):
        with self.assertRaises(Error): self.host.op_app_install("heimdall", 18080, network={"mode": "host"})
        self.listeners = "tcp LISTEN 0 100 0.0.0.0:80 0.0.0.0:*"
        with self.assertRaises(Error): self.host.op_app_install("heimdall", 80, network={"mode": "host"})
        self.assertEqual(self.host.load("apps", []), [])

    def test_host_mode_reserves_real_ports_against_later_bridge_apps(self):
        self.host.op_app_install("jellyfin", 8096, network={"mode": "host"})
        with self.assertRaises(Error): self.host.op_app_install("heimdall", 8096)

    def test_stopped_host_app_detects_new_local_port_conflict_before_start(self):
        self.host.op_app_install("jellyfin", 8096, network={"mode": "host"})
        self.containers["jellyfin"]["State"]["Status"] = "exited"
        self.listeners = "tcp LISTEN 0 100 [::]:8096 [::]:*"
        self.calls.clear()
        with self.assertRaises(Error): self.host.op_app_action("jellyfin", "start")
        self.assertFalse(any(command[:2] == ["docker", "compose"] for command in self.calls))

    def test_legacy_default_install_keeps_same_compose_recipe(self):
        self.host.op_app_install("jellyfin", 8096)
        record = self.host.load("apps", [])[0]
        stored = json.loads((self.host.directory / "apps/jellyfin/compose.json").read_text())
        self.assertEqual(stored, compose("jellyfin", str(self.host.directory / "apps/jellyfin"), self.owner.pw_uid, self.owner.pw_gid, 8096, record["data"]))
        self.assertEqual(record["network"], {"mode": "default"})

    def test_selection_rejects_untrusted_fields_invalid_mode_or_static_on_host(self):
        for network in ({"mode": "macvlan"}, {"mode": "host", "ipv4_address": "172.30.0.10"}, {"mode": "default", "name": "foreign"},
                        {"mode": "bridge", "name": "titan-test", "ipv4_address": "127.0.0.1"}, {"mode": "bridge", "command": "anything"}, {"mode": "bridge", "name": True}):
            with self.subTest(network=network):
                with self.assertRaises(Error): selection(network)

    def test_host_auxiliary_port_remapping_is_rejected(self):
        with self.assertRaises(Error): compose("deluge", "/tmp/config", 1000, 1000, 8112, "/tmp/data", {"peer_port": 19001}, {"mode": "host"})


class DemoAppNetworkTests(unittest.TestCase):
    def test_demo_create_static_install_inspect_stop_start_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = Demo(Path(directory))
            demo.call("app_network_create", name="titan-test", subnet="172.30.241.0/24", gateway="172.30.241.1")
            demo.call("app_install", app="heimdall", port=18080, network={"mode": "bridge", "name": "titan-test", "ipv4_address": "172.30.241.10"})
            details = demo.call("app_details", app="heimdall")["container"]
            self.assertEqual(details["networks"][0]["ipv4"], "172.30.241.10")
            self.assertIn("http://192.168.1.50:18080", [entry["url"] for entry in details["endpoints"]])
            self.assertIsNone(details["public_ip"])
            with self.assertRaises(Error): demo.call("app_network_remove", name="titan-test", confirmation="titan-test")
            demo.call("app_action", app="heimdall", action="stop")
            self.assertEqual(demo.call("app_details", app="heimdall")["container"]["endpoints"], [])
            demo.call("app_action", app="heimdall", action="start")
            self.assertEqual(demo.call("app_details", app="heimdall")["container"]["networks"][0]["ipv4"], "172.30.241.10")
            demo.call("app_action", app="heimdall", action="remove")
            self.assertTrue(demo.call("app_network_remove", name="titan-test", confirmation="titan-test")["ok"])
            demo._temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
