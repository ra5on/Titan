"""Verified Titan/uCore releases, staged as immutable bootc image deployments.

The release manifest binds a tested version to a digest. Container policy then
authenticates the actual image. Staging never reboots or stops running guests.
"""
import json
from contextlib import closing
import os
from pathlib import Path
import platform
import re
import sqlite3
import tempfile
import time
import urllib.parse
import urllib.request
from . import __version__, __release_stage__
from .core import Error

ALLOWED_HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com"}
STAGES = {"alpha": 0, "beta": 1, "stable": 2}
FORMAT = "titan-ucore-image-v1"
IMAGE_INFO = Path("/usr/share/titan/image-info.json")
PUBLIC_KEY = Path("/etc/titan/release-public.pem")
CONTAINER_KEY = Path("/etc/pki/containers/titan.pub")
CONTAINER_POLICY = Path("/etc/containers/policy.json")
BACKUP_DIRECTORY = Path("/var/lib/titan-agent/backups")
SHUTDOWN_SCHEDULE = Path("/run/systemd/shutdown/scheduled")
IMAGE_REPOSITORY = re.compile(r"ghcr\.io/[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*")
IMAGE_REFERENCE = re.compile(r"(ghcr\.io/[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*)@(sha256:[a-f0-9]{64})")


def strict_json(data):
    """Do not allow ambiguous duplicate keys in signed or local trust data."""
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, TypeError):
        raise Error("Ungültige JSON-Daten für das Systemimage.") from None


def architecture():
    machine = platform.machine()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    raise Error("Die CPU-Architektur wird von diesem Titan-Image nicht unterstützt.")


def image_info():
    from . import debian_updates
    if debian_updates.available():
        return debian_updates.image_info()
    try:
        value = strict_json(IMAGE_INFO.read_bytes())
    except OSError:
        raise Error("Titan benötigt sein eigenes uCore-HCI-Systemimage.", 503) from None
    if isinstance(value, dict) and value.get("platform") == "debian-preview":
        raise Error("Debian-Testsystem: Systemupdates und Rollback sind bis zur geprüften A/B-Integration gesperrt. Keine uCore-Updates installieren.", 503)
    if (not isinstance(value, dict) or value.get("format") != FORMAT or value.get("platform") != "ucore-hci"
            or value.get("architecture") != architecture()
            or not isinstance(value.get("image_repository"), str)
            or not IMAGE_REPOSITORY.fullmatch(value["image_repository"])):
        raise Error("Die installierte Titan-Imagekennung ist ungültig.")
    version(value.get("version"))
    manifest_stage(value)
    return value


def validate_image_manifest(manifest, info):
    if isinstance(manifest, dict) and (manifest.get('boot_test') != 'passed' or manifest.get('runtime_test') != 'passed'):
        raise Error('Dieses Systemimage hat die automatischen Start- und Laufzeitprüfungen nicht nachweislich bestanden. Systemupdates sind gesperrt.', 409)
    if (not isinstance(manifest, dict) or manifest.get("format") != FORMAT
            or manifest.get("platform") != "ucore-hci" or manifest.get("architecture") != info["architecture"]
            or not isinstance(manifest.get("release_stage"), str) or manifest["release_stage"] not in STAGES):
        raise Error("Das Release ist kein passendes Titan-uCore-Systemimage.")
    manifest_stage(manifest)
    reference = manifest.get("image")
    match = IMAGE_REFERENCE.fullmatch(reference) if isinstance(reference, str) else None
    if not match or match.group(1) != info["image_repository"]:
        raise Error("Das signierte Systemimage muss aus der installierten Titan-Imagequelle stammen und einen festen SHA256-Digest verwenden.")
    return reference


def deployment(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("incompatible", False), bool):
        raise Error("bootc hat einen ungültigen Bereitstellungsstatus geliefert.", 503)
    outer = value.get("image")
    if not isinstance(outer, dict) or not isinstance(outer.get("image"), dict):
        raise Error("bootc hat keine gültige Imagekennung geliefert.", 503)
    inner = outer["image"]
    reference, digest = inner.get("image"), outer.get("imageDigest")
    if (not isinstance(reference, str) or len(reference) > 1024
            or inner.get("transport") != "registry" or not isinstance(digest, str)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest)):
        raise Error("bootc hat keine gültige Registry-Imagekennung geliefert.", 503)
    result = {"image": reference, "digest": digest, "incompatible": value.get("incompatible", False)}
    image_version = outer.get("version")
    if isinstance(image_version, str) and len(image_version) <= 128:
        result["version"] = image_version
    return result


def scheduled_reboot():
    """Read systemd's scheduled shutdown record; never schedule from a read."""
    try:
        text = SHUTDOWN_SCHEDULE.read_text()
    except FileNotFoundError:
        return None
    except OSError:
        raise Error("Der geplante Neustartstatus konnte nicht gelesen werden.", 503) from None
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    try:
        timestamp = int(values["USEC"]) / 1_000_000
    except (KeyError, ValueError):
        raise Error("systemd hat einen ungültigen Neustartstatus geliefert.", 503) from None
    if timestamp <= 0 or values.get("MODE") not in ("reboot", "poweroff", "halt", "kexec"):
        raise Error("systemd hat einen ungültigen Neustartstatus geliefert.", 503)
    return {"at": timestamp, "mode": values["MODE"]}


def validate_deployment(value, info):
    """Require a compatible Titan deployment, including a digest/tag boundary."""
    if not value or value.get("incompatible"):
        raise Error("Die Bereitstellung enthält lokale Paketänderungen oder ist nicht verfügbar.", 409)
    reference, digest = value.get("image"), value.get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise Error("Der Systemimage-Digest ist ungültig.", 409)
    fixed = IMAGE_REFERENCE.fullmatch(reference) if isinstance(reference, str) else None
    tagged = re.fullmatch(re.escape(info["image_repository"]) + r":[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", reference) if isinstance(reference, str) else None
    if not ((fixed and fixed.group(1) == info["image_repository"] and fixed.group(2) == digest) or tagged):
        raise Error("Die Bereitstellung gehört nicht zur vertrauenswürdigen Titan-Imagequelle.", 409)
    version(value.get("version"))
    return info["image_repository"] + "@" + digest


def rollback_availability(state, info):
    if state.get("reboot_scheduled"):
        return False, "Ein Neustart ist bereits geplant. Weitere Systemänderungen sind gesperrt."
    if state.get("reboot_required"):
        return False, "Ein Update oder Rollback ist bereits vorbereitet. Zuerst den Neustart durchführen."
    if state.get("rollback") is None:
        return False, "Nach der ersten Installation gibt es noch keine vorherige Titan-Version. Ein Rollback wird nach dem ersten erfolgreich gestarteten Systemupdate verfügbar."
    try:
        validate_deployment(state.get("booted"), info)
        validate_deployment(state["rollback"], info)
        if state["rollback"]["digest"] == state["booted"]["digest"]:
            raise Error("Die vorherige Bereitstellung enthält dasselbe Systemimage.", 409)
    except Error as exc:
        return False, str(exc)
    return True, "Vorbereitung prüft die signierte vorherige Version erneut. Der Neustart bleibt eine separate Aktion."


def system_status():
    from . import debian_updates
    if debian_updates.available():
        return debian_updates.system_status()
    """Read immutable OS state without package refreshes or host mutations."""
    from .host import run
    info = image_info()
    value = strict_json(run(["bootc", "status", "--json", "--format-version=1"], timeout=30))
    if not isinstance(value, dict) or not isinstance(value.get("status"), dict):
        raise Error("bootc hat keinen gültigen Systemstatus geliefert.", 503)
    status = value["status"]
    booted = deployment(status.get("booted"))
    if booted is None:
        raise Error("Titan wurde nicht als bootc-Systemimage gestartet.", 503)
    staged, rollback = deployment(status.get("staged")), deployment(status.get("rollback"))
    rollback_queued = status.get("rollbackQueued", False)
    if not isinstance(rollback_queued, bool):
        raise Error("bootc hat einen ungültigen Rollbackstatus geliefert.", 503)
    result = {"platform": "ucore-hci", "update_kind": "image", "current": info["version"],
            "current_stage": manifest_stage(info), "image_repository": info["image_repository"],
            "architecture": info["architecture"], "booted": booted, "staged": staged, "rollback": rollback,
            "rollback_queued": rollback_queued, "reboot_required": staged is not None or rollback_queued,
            "automatic_reboot": False, "output": "Systemupdates erfolgen als signierte Titan-Images. Ein Neustart wird ausschließlich manuell ausgelöst."}
    result["reboot_schedule"] = scheduled_reboot()
    result["reboot_scheduled"] = result["reboot_schedule"] is not None
    result["next_boot"] = rollback if rollback_queued else staged or booted
    result["rollback_available"], result["rollback_reason"] = rollback_availability(result, info)
    return result


def version(value):
    if not isinstance(value, str) or len(value) > 128:
        raise Error("Ungültige Versionsnummer.")
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta)\.(\d+))?", value)
    if not match:
        raise Error("Ungültige Versionsnummer.")
    major, minor, patch, stage, counter = match.groups()
    return (int(major), int(minor), int(patch), STAGES[stage or "stable"], int(counter or 0))


def allowed_stage(channel, stage):
    if not isinstance(channel, str) or not isinstance(stage, str) or channel not in STAGES or stage not in STAGES:
        raise Error("Ungültiger Update-Kanal oder Entwicklungsstand.")
    return STAGES[stage] >= STAGES[channel]


def staged_version(value, stage):
    """Honor explicitly signed stages for legacy bare Alpha/Beta versions."""
    parsed = version(value)
    if not isinstance(stage, str) or stage not in STAGES:
        raise Error("Ungültiger Entwicklungsstand.")
    suffix = re.search(r"-(alpha|beta)\.[0-9]+$", value)
    if suffix:
        if suffix.group(1) != stage:
            raise Error("Version und Entwicklungsstand stimmen nicht überein.")
        return parsed
    return parsed[:3] + (STAGES[stage], 0)


def release_stage(item):
    """Conservative discovery; the signed manifest is authoritative at install."""
    if not isinstance(item, dict) or not isinstance(item.get("tag_name"), str):
        raise Error("Ungültige Release-Kennzeichnung.")
    tag = item.get("tag_name", "")
    version(tag)
    suffix = re.search(r"-(alpha|beta)\.[0-9]+$", tag)
    tag_stage = suffix.group(1) if suffix else None
    title = item.get("name")
    title = "" if title is None else title
    if not isinstance(title, str):
        raise Error("Ungültige Release-Kennzeichnung.")
    titles = set(re.findall(r"\b(alpha|beta|stable)\b", title.lower()))
    if len(titles) > 1 or (titles and tag_stage and tag_stage not in titles):
        raise Error("Widersprüchliche Release-Kennzeichnung.")
    titled = next(iter(titles), None)
    flag = item.get("prerelease", False)
    if not isinstance(flag, bool) or (flag and titled == "stable"):
        raise Error("Ungültige Release-Kennzeichnung.")
    return tag_stage or titled or ("alpha" if flag else "stable")


def manifest_stage(manifest):
    if not isinstance(manifest, dict):
        raise Error("Ungültiges Update-Manifest.")
    version(manifest.get("version"))
    suffix = re.search(r"-(alpha|beta)\.[0-9]+$", manifest["version"])
    stage = manifest.get("release_stage", suffix.group(1) if suffix else "alpha")
    if not isinstance(stage, str) or stage not in STAGES or (suffix and stage != suffix.group(1)):
        raise Error("Ungültiger Entwicklungsstand im signierten Manifest.")
    return stage


def repository(value):
    if not isinstance(value, str) or len(value) > 256 or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise Error("Ungültiges GitHub-Repository.")
    return value


def validate_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.port not in (None, 443) or parts.username:
        raise Error("Update-Download verwendet keine erlaubte GitHub-Adresse.")


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_url(newurl)
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        # Never forward GitHub credentials to asset hosts.
        if urllib.parse.urlsplit(newurl).hostname != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected


def fetch(url, token=None, binary=False, maximum=8 * 1024 * 1024):
    validate_url(url)
    headers = {"User-Agent": "Titan/" + __version__,
               "Accept": "application/octet-stream" if binary else "application/vnd.github+json"}
    if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
        headers["Authorization"] = "Bearer " + token
    try:
        with urllib.request.build_opener(Redirect()).open(urllib.request.Request(url, headers=headers), timeout=30) as response:
            data = response.read(maximum + 1)
            if len(data) > maximum:
                raise Error("Update-Datei ist zu groß.")
            return data
    except Error:
        raise
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code == 404:
            raise Error("Noch kein Release vorhanden oder privates Repository ohne Lesetoken.", 404)
        raise Error("GitHub ist momentan nicht erreichbar.", 503)


def read_token():
    path = Path("/etc/titan/github-token")
    return path.read_text().strip() if path.exists() else None


def verify_manifest(manifest, signature, key):
    from .host import run
    run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(key),
         "-in", str(manifest), "-sigfile", str(signature)])
    return strict_json(Path(manifest).read_bytes())


def verified_release(release, token=None):
    if not PUBLIC_KEY.is_file():
        raise Error("Vertrauenswürdiger Release-Schlüssel fehlt.")
    assets = release.get("assets", [])
    if (not isinstance(assets, list) or any(not isinstance(item, dict)
            or not isinstance(item.get("name"), str) or not isinstance(item.get("url"), str)
            for item in assets) or len({item["name"] for item in assets}) != len(assets)
            or not isinstance(release.get("html_url"), str)):
        raise Error("GitHub hat ungültige Release-Dateien geliefert.", 503)
    assets = {item["name"]: item["url"] for item in assets}
    if "manifest.json" not in assets or "manifest.json.sig" not in assets:
        raise Error("Release enthält kein signiertes Update-Manifest.")
    with tempfile.TemporaryDirectory(prefix="titan-manifest-") as temporary:
        directory = Path(temporary)
        manifest = directory / "manifest.json"
        signature = directory / "manifest.json.sig"
        manifest.write_bytes(fetch(assets["manifest.json"], token, binary=True, maximum=16384))
        signature.write_bytes(fetch(assets["manifest.json.sig"], token, binary=True, maximum=1024))
        value = verify_manifest(manifest, signature, PUBLIC_KEY)
    return value, assets


def check(repo, channel="stable", token=None):
    from . import debian_updates
    if debian_updates.available():
        return debian_updates.check(repo, channel, token)
    repo = repository(repo)
    if not isinstance(channel, str) or channel not in STAGES:
        raise Error("Ungültiger Update-Kanal.")
    result = {"current": __version__, "current_stage": __release_stage__, "checked": time.time(), "available": False,
              "repository": repo, "channel": channel, "update_kind": "image", "automatic_reboot": False}
    try:
        info = image_info()
        result.update(system_status())
        releases = strict_json(fetch(f"https://api.github.com/repos/{repo}/releases?per_page=30", token))
        if not isinstance(releases, list):
            raise Error("GitHub hat keine gültige Release-Liste geliefert.", 503)
        candidates = []
        for item in releases:
            if not isinstance(item, dict) or not isinstance(item.get("draft", False), bool) or item.get("draft"):
                continue
            try:
                stage = release_stage(item)
                if allowed_stage(channel, stage):
                    candidates.append((staged_version(item["tag_name"], stage), item, stage))
            except (Error, KeyError):
                continue
        if not candidates:
            result["message"] = "Noch kein passendes Titan-Systemimage veröffentlicht."
            return result
        _, release, stage = max(candidates, key=lambda item: item[0])
        manifest, assets = verified_release(release, token)
        image = validate_image_manifest(manifest, info)
        if manifest_stage(manifest) != stage or version(manifest["version"]) != version(release["tag_name"]):
            raise Error("Signiertes Image-Manifest und GitHub-Release stimmen nicht überein.")
        pending = result["reboot_required"] or result.get("reboot_scheduled", False)
        incompatible = result.get("booted", {}).get("incompatible", False)
        result.update(latest=release["tag_name"], latest_stage=stage, notes=release.get("body", ""),
                      url=release["html_url"], available=not pending and not incompatible and staged_version(release["tag_name"], stage) > staged_version(info["version"], manifest_stage(info)),
                      assets=assets, signed=True, image=image, signature_verified=True)
        if result.get("reboot_scheduled"):
            result["message"] = "Ein Systemneustart ist bereits geplant. Neue Updates bleiben bis nach dem Neustart gesperrt."
        elif pending:
            result["message"] = "Ein Systemimage ist vorbereitet. Der Neustart muss manuell erfolgen; vorher laufende virtuelle Maschinen und Dienste geordnet beenden."
        elif incompatible:
            result["message"] = "Lokale Paketänderungen verhindern Imageupdates. Titan benötigt ein unverändertes vollständiges Systemimage."
        return result
    except Error as exc:
        result["available"] = False
        result["error"] = str(exc)
        return result


def verify_container_policy(info):
    """Fail closed even if the installed policy was relaxed outside Titan."""
    try:
        policy = strict_json(CONTAINER_POLICY.read_bytes())
        container_key = CONTAINER_KEY.read_bytes().strip()
        release_key = PUBLIC_KEY.read_bytes().strip()
    except OSError:
        raise Error("Vertrauensrichtlinie oder öffentlicher Imageschlüssel fehlt.") from None
    transports = policy.get("transports") if isinstance(policy, dict) else None
    docker = transports.get("docker") if isinstance(transports, dict) else None
    rule = docker.get(info["image_repository"]) if isinstance(docker, dict) else None
    overrides = any(isinstance(scope, str) and (scope.startswith(info["image_repository"] + ":")
                    or scope.startswith(info["image_repository"] + "@")) for scope in docker or {})
    if (not isinstance(policy, dict) or policy.get("default") != [{"type": "reject"}]
            or overrides or not container_key or container_key != release_key or not isinstance(rule, list) or len(rule) != 1
            or not isinstance(rule[0], dict) or rule[0].get("type") != "sigstoreSigned"
            or rule[0].get("keyPath") != str(CONTAINER_KEY)
            or rule[0].get("signedIdentity") != {"type": "matchRepository"}):
        raise Error("Die Titan-Imagequelle muss den vertrauenswürdigen Imageschlüssel erzwingen.")


def backup_configuration(database):
    BACKUP_DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = BACKUP_DIRECTORY / f"configuration-{time.time_ns()}.sqlite3"
    with closing(sqlite3.connect(f"file:{Path(database).absolute()}?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
    os.chmod(backup, 0o600)
    return str(backup)


def validate_system_action(operation, arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"expected_digest", "confirmation"}:
        raise Error("Systemimage-Digest und ausdrückliche Bestätigung sind erforderlich.")
    digest = arguments["expected_digest"]
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise Error("Ein gültiger erwarteter Systemimage-Digest ist erforderlich.")
    expected = {"update_rollback": "ROLLBACK", "system_reboot": "NEUSTART"}.get(operation)
    if expected is None or arguments["confirmation"] != expected:
        raise Error("Bitte die Systemaktion ausdrücklich bestätigen.")


def authenticate_deployment(repo, target, info):
    """Bind an existing local deployment to an independently signed release.

    rollback does not fetch an image or offer --enforce-container-sigpolicy.
    Authenticate the exact local digest before reordering boot entries; this
    also supports installers whose initial deployment has no signature flag.
    """
    reference = validate_deployment(target, info)
    repo = repository(repo)
    target_version = target["version"].removeprefix("v")
    release = strict_json(fetch(f"https://api.github.com/repos/{repo}/releases/tags/v{target_version}", read_token()))
    if not isinstance(release, dict) or release.get("draft", False) is not False:
        raise Error("Die vorherige Bereitstellung besitzt kein veröffentlichtes Titan-Release.", 409)
    manifest, _ = verified_release(release, read_token())
    verified_image = validate_image_manifest(manifest, info)
    if (verified_image != reference or version(manifest["version"]) != version(target["version"])
            or version(release.get("tag_name")) != version(target["version"])
            or manifest_stage(manifest) != release_stage(release)):
        raise Error("Die signierte Titan-Version stimmt nicht mit der lokalen Bereitstellung überein.", 409)
    verify_container_policy(info)
    return reference


def rollback(repo, expected_digest, confirmation, database):
    from . import debian_updates
    if debian_updates.available():
        return debian_updates.rollback(repo, expected_digest, confirmation, database)
    """Queue the authenticated existing rollback entry without restarting."""
    validate_system_action("update_rollback", {"expected_digest": expected_digest, "confirmation": confirmation})
    info = image_info()
    current = system_status()
    allowed, reason = rollback_availability(current, info)
    if not allowed:
        raise Error(reason, 409)
    target = current["rollback"]
    if target["digest"] != expected_digest:
        raise Error("Die vorherige Systemversion hat sich geändert. Status erneut laden.", 409)
    image = authenticate_deployment(repo, target, info)
    backup = backup_configuration(database)
    # Recheck after downloads/backup: a manual bootc action may have intervened.
    fresh = system_status()
    allowed, reason = rollback_availability(fresh, info)
    if (not allowed or fresh["booted"]["digest"] != current["booted"]["digest"]
            or fresh["rollback"] != target):
        raise Error(reason if not allowed else "Die Systembereitstellung hat sich geändert. Status erneut laden.", 409)
    from .host import run
    run(["bootc", "rollback"], timeout=120)
    prepared = system_status()
    if (not prepared.get("rollback_queued") or prepared.get("staged") is not None
            or prepared.get("rollback") != target or prepared["booted"]["digest"] != current["booted"]["digest"]):
        raise Error("Das Rollback wurde nicht vollständig vorbereitet. bootc-Status prüfen.", 503)
    return {"ok": True, "version": target["version"], "image": image, "backup": backup,
            "rollback": target, "rollback_queued": True, "reboot_required": True, "automatic_reboot": False,
            "message": "Rollback vorbereitet. Ein separater Neustart aktiviert die vorherige Systemversion. Dateien, Apps und Daten in /var bleiben erhalten; /etc kehrt zum Stand der vorherigen Bereitstellung zurück. Die Titan-Konfiguration wurde gesichert und wird nicht automatisch zurückgesetzt."}


def reboot(repo, expected_digest, confirmation, database):
    from . import debian_updates
    if debian_updates.available():
        return debian_updates.reboot(repo, expected_digest, confirmation, database)
    """Schedule a regular systemd reboot after the job can reach the browser."""
    validate_system_action("system_reboot", {"expected_digest": expected_digest, "confirmation": confirmation})
    info = image_info()
    current = system_status()
    if current.get("reboot_scheduled"):
        raise Error("Ein Neustart ist bereits geplant.", 409)
    target = current.get("next_boot")
    validate_deployment(current.get("booted"), info)
    validate_deployment(target, info)
    if target["digest"] != expected_digest:
        raise Error("Das Systemimage für den nächsten Start hat sich geändert. Status erneut laden.", 409)
    if current.get("reboot_required"):
        authenticate_deployment(repo, target, info)
    from .host import run
    # Include every active libvirt domain, even ones created outside Titan.
    guests = [name.strip() for name in run(["virsh", "list", "--name"], timeout=30).splitlines() if name.strip()]
    if guests:
        raise Error("Neustart gesperrt. Diese virtuellen Maschinen zuerst geordnet herunterfahren: " + ", ".join(guests), 409)
    backup = backup_configuration(database)
    fresh = system_status()
    if (fresh.get("reboot_scheduled") or fresh.get("next_boot") != target
            or fresh["booted"]["digest"] != current["booted"]["digest"]):
        raise Error("Der Systemstatus hat sich geändert. Status erneut laden.", 409)
    # +1 gives the RPC/job/audit responses time to complete. systemd gracefully
    # stops services, including Docker; never use bootc --apply or forced reboot.
    run(["shutdown", "-r", "+1", "Titan: ausdrücklich bestätigter Systemneustart"], timeout=30)
    schedule = scheduled_reboot()
    if schedule is None or schedule["mode"] != "reboot":
        raise Error("systemd hat den Neustart nicht bestätigt. Systemstatus prüfen.", 503)
    return {"ok": True, "reboot_scheduled": True, "reboot_schedule": schedule, "backup": backup,
            "next_boot": target, "delay_seconds": 60, "automatic_reboot": False,
            "message": "Neustart in etwa einer Minute geplant. systemd beendet die Dienste geordnet. Danach die Oberfläche erneut öffnen; ein vorbereitetes Update oder Rollback wird dabei aktiviert."}


def install(repo, channel, expected_version, database):
    from . import debian_updates
    if debian_updates.available():
        return debian_updates.install(repo, channel, expected_version, database)
    """Stage a verified digest; activation is deliberately a separate reboot."""
    repo = repository(repo)
    version(expected_version)
    if not isinstance(channel, str) or channel not in STAGES:
        raise Error("Ungültiger Update-Kanal.")
    token = read_token()
    release = check(repo, channel, token)
    if release.get("error"):
        raise Error(release["error"])
    if not release.get("available") or release.get("latest") != expected_version:
        raise Error("Die verfügbare Version hat sich geändert oder ein Neustart steht aus. Bitte erneut prüfen.", 409)
    if not release.get("signed"):
        raise Error("Release enthält kein signiertes Update-Manifest.")
    # Always fetch and authenticate again. Cached API offers are not trust input.
    assets = release.get("assets", {})
    manifest, _ = verified_release({"assets": [{"name": name, "url": url} for name, url in assets.items()],
                                    "html_url": release.get("url", "")}, token)
    info = image_info()
    stage = manifest_stage(manifest)
    if not allowed_stage(channel, stage) or stage != release.get("latest_stage"):
        raise Error("Der signierte Entwicklungsstand passt nicht zum gewählten Update-Kanal oder Release.")
    if version(manifest["version"]) != version(expected_version):
        raise Error("Manifest und Release-Version stimmen nicht überein.")
    image = validate_image_manifest(manifest, info)
    if staged_version(expected_version, stage) <= staged_version(info["version"], manifest_stage(info)):
        raise Error("Die Update-Version ist nicht neuer als das gestartete Titan-Systemimage.", 409)
    current = system_status()
    if current["booted"]["incompatible"]:
        raise Error("Das System enthält lokale Paketänderungen. Titan verwaltet ausschließlich vollständige Systemimages.", 409)
    if current["reboot_required"] or current.get("reboot_scheduled"):
        raise Error("Ein anderes Systemimage oder Rollback ist bereits vorbereitet. Zuerst manuell neu starten.", 409)
    booted_reference = current["booted"]["image"]
    if not (booted_reference.startswith(info["image_repository"] + "@sha256:")
            or booted_reference.startswith(info["image_repository"] + ":")):
        raise Error("Das gestartete System gehört nicht zur vertrauenswürdigen Titan-Imagequelle.", 409)
    if current["booted"]["digest"] == image.rsplit("@", 1)[1]:
        raise Error("Dieses Systemimage ist bereits gestartet.", 409)
    verify_container_policy(info)
    backup = backup_configuration(database)
    from .host import run
    run(["bootc", "switch", "--enforce-container-sigpolicy", image], timeout=1800)
    # Verify that bootc actually staged the requested payload instead of treating
    # an unexpectedly successful/no-op process as a completed installation.
    prepared = system_status()
    staged = prepared.get("staged")
    if (not staged or staged["digest"] != image.rsplit("@", 1)[1]
            or staged["image"] != image or staged["incompatible"]
            or version(staged.get("version")) != version(expected_version)):
        raise Error("Das angeforderte Systemimage wurde nicht vollständig vorbereitet. bootc-Status prüfen.", 503)
    return {"ok": True, "version": expected_version, "image": image, "backup": backup,
            "update_kind": "image", "staged": staged, "reboot_required": True, "automatic_reboot": False,
            "message": "Systemimage vorbereitet. Titan und laufende virtuelle Maschinen bleiben aktiv. Nach geordnetem Beenden der Dienste manuell neu starten, um das Update zu aktivieren."}
