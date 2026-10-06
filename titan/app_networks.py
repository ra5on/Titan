"""Validated Docker bridge selection and observed app addresses.

Network configuration is deliberately separate from private app settings.
Only Docker's local bridge and host drivers are deployable here. Host mode
uses the recipe's actual ports: Compose port mappings never accompany it.
"""
import ipaddress
import json
import re

from .core import Error


def _run(*arguments, **kwargs):
    from .host import run
    return run(*arguments, **kwargs)


def network_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", value):
        raise Error("Netzwerkname: 1–63 Buchstaben, Ziffern, Punkt, _ oder -.")
    return value


def selection(value=None):
    if value is None:
        return {"mode": "default"}
    if not isinstance(value, dict) or set(value) - {"mode", "name", "ipv4_address"}:
        raise Error("Ungültige App-Netzwerkeinstellungen.")
    mode = value.get("mode", "default")
    if mode not in ("default", "bridge", "host"):
        raise Error("Netzwerkmodus muss Standard, Bridge oder Host sein.")
    name, address = value.get("name", ""), value.get("ipv4_address", "")
    if not isinstance(name, str) or not isinstance(address, str):
        raise Error("Netzwerk und IPv4-Adresse müssen Text sein.")
    if (name or address) and mode != "bridge":
        raise Error("Eine feste IP-Adresse benötigt ein benutzerdefiniertes Bridge-Netzwerk.")
    result = {"mode": mode}
    if name:
        result["name"] = network_name(name)
    if address:
        if not name or name in ("bridge", "host", "none"):
            raise Error("Eine feste IP-Adresse benötigt ein benutzerdefiniertes Bridge-Netzwerk.")
        try:
            parsed = ipaddress.IPv4Address(address)
        except ValueError:
            raise Error("Ungültige feste IPv4-Adresse.") from None
        if parsed.is_unspecified or parsed.is_multicast or parsed.is_loopback or parsed.is_link_local:
            raise Error("Diese IPv4-Adresse kann keinem App-Netzwerk zugeordnet werden.")
        result["ipv4_address"] = str(parsed)
    return result


def apply_selection(definition, app, value=None):
    network = selection(value)
    service = definition["services"][app]
    if network["mode"] == "host":
        service.pop("ports", None)
        service["network_mode"] = "host"
    elif network["mode"] == "bridge":
        name = network.get("name")
        if not name or name == "bridge":
            service["network_mode"] = "bridge"
        else:
            service["networks"] = {"selected": ({"ipv4_address": network["ipv4_address"]} if network.get("ipv4_address") else {})}
            definition["networks"] = {"selected": {"external": True, "name": name}}
    return definition


RESERVED_NETWORKS = frozenset(("bridge", "host", "none", "ingress", "docker_gwbridge"))


def validate_create(name, subnet=None, gateway=None, internal=False):
    name = network_name(name)
    if name.lower() in RESERVED_NETWORKS:
        raise Error("Dieser Netzwerkname ist für Docker reserviert. Einen eigenen Namen wählen.")
    if type(internal) is not bool:
        raise Error("Internes Netzwerk muss ein boolescher Wert sein.")
    if gateway is not None and not isinstance(gateway, str):
        raise Error("IPv4-Gateway muss eine Adresse als Text sein.")
    if subnet in (None, ""):
        if gateway:
            raise Error("Ein eigenes Gateway benötigt ein IPv4-Subnetz.")
        return {"name": name, "subnet": None, "gateway": None, "internal": internal}
    if not isinstance(subnet, str):
        raise Error("IPv4-Subnetz mit Präfix angeben, zum Beispiel 172.30.10.0/24.")
    try:
        parsed = ipaddress.IPv4Network(subnet, strict=True)
    except ValueError:
        raise Error("Ungültiges IPv4-Subnetz. Die Adresse muss die Netzadresse sein.") from None
    private = [ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if parsed.prefixlen > 30 or not any(parsed.subnet_of(value) for value in private):
        raise Error("Ein privates IPv4-Subnetz mit mindestens zwei nutzbaren Adressen wählen.")
    try:
        address = ipaddress.IPv4Address(gateway or str(parsed.network_address + 1))
    except (ValueError, TypeError):
        raise Error("Ungültige IPv4-Gateway-Adresse.") from None
    if address not in parsed or address in (parsed.network_address, parsed.broadcast_address):
        raise Error("Das Gateway muss eine nutzbare Adresse innerhalb des Subnetzes sein.")
    return {"name": name, "subnet": str(parsed), "gateway": str(address), "internal": internal}


def available_subnet(occupied):
    """Choose a private /24 only after checking Docker networks and host routes."""
    used = [ipaddress.IPv4Network(value, strict=False) for value in occupied]
    # Avoid the common Docker default ranges first, then consider the remaining
    # RFC1918 172/12 space. Never guess when all candidates are in use.
    for block in (30, 31, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16):
        for index in range(256):
            candidate = ipaddress.IPv4Network(f"172.{block}.{index}.0/24")
            if not any(candidate.overlaps(value) for value in used):
                return str(candidate)
    raise Error("Kein freies privates Subnetz gefunden. Unter Erweitert ein passendes Subnetz wählen.", 409)


class AppNetworkMixin:
    @staticmethod
    def _network_json(arguments):
        try:
            value = json.loads(_run(arguments, timeout=30))
        except (ValueError, TypeError):
            raise Error("Docker liefert einen ungültigen Netzwerkstatus.", 503) from None
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise Error("Docker liefert einen ungültigen Netzwerkstatus.", 503)
        return value

    def _docker_networks(self):
        output = _run(["docker", "network", "ls", "--no-trunc", "--format", "{{.ID}}"], timeout=30)
        identifiers = output.splitlines()
        if not identifiers:
            return []
        if len(identifiers) > 1024 or any(not re.fullmatch(r"[a-f0-9]{12,64}", value) for value in identifiers):
            raise Error("Docker liefert ungültige Netzwerkkennungen.", 503)
        return self._network_json(["docker", "network", "inspect", *identifiers])

    def _docker_network(self, name):
        name = network_name(name)
        value = self._network_json(["docker", "network", "inspect", name])
        if len(value) != 1 or value[0].get("Name") != name or not re.fullmatch(r"[a-f0-9]{12,64}", str(value[0].get("Id", ""))):
            raise Error("Docker liefert kein eindeutiges Netzwerk.", 503)
        return value[0]

    @staticmethod
    def _network_subnets(item):
        result = []
        for config in (item.get("IPAM", {}).get("Config") or []):
            try:
                subnet = ipaddress.ip_network(config["Subnet"], strict=True)
                gateway = config.get("Gateway", "")
                if gateway and ipaddress.ip_address(gateway) not in subnet:
                    continue
                result.append({"subnet": str(subnet), "gateway": gateway or "", "family": subnet.version})
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _network_summary(self, item, container_rows=None):
        name = item.get("Name", "")
        selectable = (item.get("Driver") == "bridge" and item.get("Scope", "local") == "local" and
                      not item.get("ConfigOnly") and not item.get("Ingress"))
        configured = next((value for value in self.load("app-networks", []) if value.get("name") == name), None)
        labels = item.get("Labels") or {}
        managed = bool(configured and configured.get("id") == item.get("Id") and
                       labels.get("io.titan.managed") == "true" and labels.get("io.titan.network") == name)
        subnets = self._network_subnets(item)
        endpoints = [{"name": value.get("Name", ""),
                    "ipv4": value.get("IPv4Address", "").split("/", 1)[0], "ipv6": value.get("IPv6Address", "").split("/", 1)[0]}
                    for value in (item.get("Containers") or {}).values()]
        # Stopped containers can still refer to a network without an active
        # endpoint. Keep that dependency visible and prevent deleting it.
        for row in container_rows or []:
            attached = (row.get("NetworkSettings") or {}).get("Networks") or {}
            if name in attached or (row.get("HostConfig") or {}).get("NetworkMode") in (name, item.get("Id")):
                container_name = str(row.get("Name", "")).lstrip("/")
                if not any(value["name"] == container_name for value in endpoints):
                    info = attached.get(name) or {}
                    endpoints.append({"name": container_name, "ipv4": info.get("IPAddress", ""),
                                      "ipv6": info.get("GlobalIPv6Address", ""), "state": (row.get("State") or {}).get("Status", "unknown")})
        used_by = [app["id"] for app in self.load("apps", []) if selection(app.get("network")).get("name") == name]
        protected = name.lower() in RESERVED_NETWORKS or not selectable or not managed
        reason = ("Docker-Systemnetzwerk" if name.lower() in RESERVED_NETWORKS else
                  "Wird von Docker oder einem App-Paket verwaltet" if not managed else
                  "Kein verwaltetes lokales Bridge-Netzwerk" if not selectable else
                  "Wird noch von Containern oder einem App-Paket verwendet" if endpoints or used_by else "")
        return {"id": item.get("Id", ""), "name": name, "driver": item.get("Driver", ""),
                "internal": item.get("Internal") is True, "managed": managed, "selectable": selectable,
                "scope": item.get("Scope", "local"), "removable": not protected and not endpoints and not used_by,
                "deletion_reason": reason,
                "static_ipv4": selectable and name != "bridge" and any(value["family"] == 4 for value in subnets),
                "subnets": subnets, "containers": endpoints, "used_by": used_by}

    @staticmethod
    def _host_addresses():
        try:
            entries = json.loads(_run(["ip", "-j", "address", "show", "up"], timeout=15))
            result = []
            for item in entries:
                # Docker and VM bridge addresses are internal routing endpoints,
                # rather than the NAS address users normally open in a browser.
                interface = item.get("ifname", "")
                if interface.startswith(("docker", "br-", "veth", "virbr", "tun", "tap")):
                    continue
                for info in item.get("addr_info", []):
                    if info.get("family") not in ("inet", "inet6"):
                        continue
                    address = ipaddress.ip_address(info.get("local", ""))
                    if address.is_link_local or address.is_multicast or address.is_unspecified:
                        continue
                    result.append({"address": str(address), "family": address.version, "interface": interface,
                                   "scope": "loopback" if address.is_loopback else "lan"})
            return result
        except (Error, ValueError, TypeError, KeyError):
            return []

    def op_app_networks(self):
        try:
            items = self._docker_networks()
            rows = self._app_inspected_containers() if items else []
            networks = [self._network_summary(item, rows) for item in items]
        except (Error, ValueError, TypeError, KeyError) as exc:
            return {"available": False, "networks": [], "host_addresses": self._host_addresses(),
                    "public_ip": None, "warnings": [str(exc)]}
        return {"available": True, "networks": sorted(networks, key=lambda item: item["name"]),
                "host_addresses": self._host_addresses(), "public_ip": None, "warnings": []}

    def op_app_network_create(self, name, subnet=None, gateway=None, internal=False):
        requested = validate_create(name, subnet, gateway, internal)
        existing = self._docker_networks()
        if any(item.get("Name") == name for item in existing):
            raise Error("Dieses Docker-Netzwerk existiert bereits.", 409)
        if any(item.get("name") == name for item in self.load("app-networks", [])):
            raise Error("Dieser Netzwerkname ist bereits in Titan reserviert. Den vorhandenen Eintrag zuerst prüfen.", 409)
        occupied = []
        for item in existing:
            for value in self._network_subnets(item):
                if value["family"] == 4:
                    occupied.append(value["subnet"])
                    if requested["subnet"] and ipaddress.IPv4Network(requested["subnet"]).overlaps(ipaddress.IPv4Network(value["subnet"])):
                        raise Error(f"Subnetz überschneidet sich mit Docker-Netzwerk {item.get('Name', '')}.", 409)
        try:
            routes = json.loads(_run(["ip", "-j", "-4", "route", "show", "table", "all"], timeout=15))
        except (ValueError, TypeError):
            raise Error("Host-Routen können vor der Netzwerkerstellung nicht geprüft werden.", 503) from None
        if not isinstance(routes, list):
            raise Error("Ungültiger Host-Routenstatus.", 503)
        for route in routes:
            if not isinstance(route, dict):
                raise Error("Ungültiger Host-Routenstatus.", 503)
            target = route.get("dst", "default")
            if target == "default":
                continue
            try:
                used = ipaddress.IPv4Network(target, strict=False)
            except (ValueError, TypeError):
                continue
            occupied.append(str(used))
            if requested["subnet"] and ipaddress.IPv4Network(requested["subnet"]).overlaps(used):
                raise Error(f"Subnetz überschneidet sich mit einer Host-Route ({used}).", 409)
        if not requested["subnet"]:
            requested = validate_create(name, available_subnet(occupied), internal=internal)
        command = ["docker", "network", "create", "--driver", "bridge", "--subnet", requested["subnet"],
                   "--gateway", requested["gateway"], "--label", "io.titan.managed=true", "--label", "io.titan.network=" + name]
        if internal:
            command.append("--internal")
        command.append(name)
        identifier = _run(command, timeout=60).strip()
        if not re.fullmatch(r"[a-f0-9]{12,64}", identifier):
            raise Error("Docker lieferte keine gültige Kennung für das neue Netzwerk.", 503)
        actual = self._docker_network(name)
        expected_subnets = [{"subnet": requested["subnet"], "gateway": requested["gateway"], "family": 4}]
        if (actual["Id"] != identifier or actual.get("Driver") != "bridge" or
                actual.get("Internal") is not internal or self._network_subnets(actual) != expected_subnets or
                (actual.get("Labels") or {}).get("io.titan.network") != name or
                (actual.get("Labels") or {}).get("io.titan.managed") != "true"):
            raise Error("Erstelltes Netzwerk stimmt nicht mit den angeforderten Einstellungen überein.", 503)
        records = self.load("app-networks", [])
        records.append({**requested, "id": actual["Id"]})
        self.save("app-networks", records)
        return {"ok": True, "network": self._network_summary(actual),
                "message": f"Netzwerk {name} ist angelegt. Subnetz: {requested['subnet']}."}

    def op_app_network_remove(self, name, confirmation):
        name = network_name(name)
        if confirmation != name:
            raise Error("Zum Entfernen den Netzwerknamen bestätigen.")
        item = self._docker_network(name)
        summary = self._network_summary(item, self._app_inspected_containers())
        if not summary["managed"] or not summary["selectable"] or name.lower() in RESERVED_NETWORKS:
            raise Error("Titan entfernt ausschließlich selbst angelegte Bridge-Netzwerke.", 403)
        if summary["containers"] or summary["used_by"]:
            raise Error("Netzwerk wird noch von einer App oder einem Container benutzt.", 409)
        _run(["docker", "network", "rm", item["Id"]], timeout=30)
        self.save("app-networks", [value for value in self.load("app-networks", []) if value.get("name") != name])
        return {"ok": True, "name": name, "message": f"Netzwerk {name} ist entfernt."}

    def _app_network_validate(self, value, app=None, record=None):
        network = selection(value)
        if network["mode"] != "bridge":
            return network, None
        name = network.get("name", "bridge")
        item = self._docker_network(name)
        summary = self._network_summary(item)
        if not summary["selectable"]:
            raise Error("Nur lokale Bridge-Netzwerke können für Apps ausgewählt werden.")
        if record and record.get("network_id") and record["network_id"] != item["Id"]:
            raise Error("Das ausgewählte Netzwerk wurde ersetzt. App-Netzwerkkonfiguration zuerst prüfen.", 409)
        if network.get("ipv4_address"):
            if not summary["static_ipv4"]:
                raise Error("Dieses Netzwerk erlaubt keine feste IPv4-Adresse.")
            address = ipaddress.IPv4Address(network["ipv4_address"])
            eligible = [value for value in summary["subnets"] if value["family"] == 4 and address in ipaddress.IPv4Network(value["subnet"])]
            if not eligible or any(address in (ipaddress.IPv4Network(value["subnet"]).network_address,
                       ipaddress.IPv4Network(value["subnet"]).broadcast_address) or str(address) == value["gateway"] for value in eligible):
                raise Error("Feste IPv4-Adresse muss eine freie Hostadresse des gewählten Subnetzes sein.")
            for endpoint in (item.get("Containers") or {}).values():
                if endpoint.get("IPv4Address", "").split("/", 1)[0] == str(address) and endpoint.get("Name") != "titan-" + str(app):
                    raise Error("Feste IPv4-Adresse wird bereits von einem Container benutzt.", 409)
            for config in (item.get("IPAM", {}).get("Config") or []):
                if str(address) in (config.get("AuxiliaryAddresses") or {}).values():
                    raise Error("Feste IPv4-Adresse ist in der Docker-Netzwerkkonfiguration reserviert.", 409)
            for installed in self.load("apps", []):
                saved = selection(installed.get("network"))
                if installed.get("id") != app and saved.get("name") == name and saved.get("ipv4_address") == str(address):
                    raise Error("Feste IPv4-Adresse ist für eine andere Titan-App reserviert.", 409)
        return network, item["Id"]

    @staticmethod
    def _host_ports_available(publications):
        output = _run(["ss", "-H", "-lnut"], timeout=15)
        occupied = set()
        for line in output.splitlines():
            fields = line.split()
            if len(fields) < 5:
                continue
            match = re.search(r":([0-9]+)$", fields[4])
            if match:
                occupied.add((int(match[1]), "udp" if fields[0].startswith("udp") else "tcp"))
        if any((item["host"], item["protocol"]) in occupied for item in publications):
            raise Error("Ein benötigter Host-Port wird bereits von einem Dienst benutzt. Bridge mit anderem Webport wählen.", 409)

    def _app_address_summary(self, container, record, networks=None, addresses=None):
        addresses = self._host_addresses() if addresses is None else addresses
        actual = container.get("NetworkSettings", {})
        selected = container.get("HostConfig", {}).get("NetworkMode", "")
        infos, warnings = [], []
        if networks is None:
            networks = {}
            for name in (actual.get("Networks") or {}):
                try:
                    networks[name] = self._docker_network(name)
                except Error as exc:
                    warnings.append(str(exc))
        for name, attached in (actual.get("Networks") or {}).items():
            info = networks.get(name, {})
            infos.append({"name": name, "driver": info.get("Driver", "host" if selected == "host" else ""),
                          "ipv4": attached.get("IPAddress", ""), "ipv6": attached.get("GlobalIPv6Address", ""),
                          "gateway": attached.get("Gateway", ""), "ipv6_gateway": attached.get("IPv6Gateway", ""),
                          "internal": info.get("Internal") is True})
        endpoints = []
        if container.get("State", {}).get("Status") in ("running", "restarting"):
            from .catalog import APPS
            target = record["port"] if APPS[record["id"]].get("dynamic_web_port") else APPS[record["id"]]["port"]
            bindings = actual.get("Ports", {}).get(f"{target}/tcp") or [] if actual.get("Ports") else []
            if selected == "host":
                bindings = [{"HostIp": "", "HostPort": str(target)}]
            for binding in bindings:
                bind_address = binding.get("HostIp", "")
                candidates = addresses
                if bind_address not in ("", "0.0.0.0", "::"):
                    candidates = [item for item in addresses if item["address"] == bind_address]
                elif bind_address == "0.0.0.0":
                    candidates = [item for item in addresses if item["family"] == 4]
                elif bind_address == "::":
                    candidates = [item for item in addresses if item["family"] == 6]
                for address in candidates:
                    host = "[" + address["address"] + "]" if address["family"] == 6 else address["address"]
                    entry = {"url": f"{record.get('scheme', 'http')}://{host}:{binding['HostPort']}",
                             "address": address["address"], "port": int(binding["HostPort"]),
                             "scope": address.get("scope", "lan"), "source": "host" if selected == "host" else "published"}
                    if entry not in endpoints:
                        endpoints.append(entry)
        return {"network_mode": selected, "networks": infos, "host_addresses": addresses,
                "endpoints": endpoints, "public_ip": None, "network_warnings": warnings}
