"""Signed release discovery and shared verification for Debian A/B updates."""


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

UPDATE_KINDS = {"all", "titan", "system"}


PUBLIC_KEY = Path("/etc/titan/release-public.pem")


BACKUP_DIRECTORY = Path("/var/lib/titan-agent/backups")


SHUTDOWN_SCHEDULE = Path("/run/systemd/shutdown/scheduled")


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


def selection_kind(value):
    if not isinstance(value, str) or value not in UPDATE_KINDS:
        raise Error("Ungültiger Update-Bereich.")
    return value


def release_metadata(value):
    """Normalize legacy identities without trusting unsigned GitHub labels."""
    core = {"update_kind", "titan_version", "titan_stage", "titan_source_commit", "system_revision"}
    present = core.intersection(value)
    if not present:
        parsed = version(value.get("version"))
        return {"release_kind": "titan", "titan_version": ".".join(map(str, parsed[:3])),
                "titan_stage": value["release_stage"], "titan_source_commit": value.get("source_commit"), "system_revision": 0,
                "package_changes": [], "security_summary": None}
    if present != core or not isinstance(value["update_kind"], str) or value["update_kind"] not in ("titan", "system"):
        raise Error("Unvollständiger oder ungültiger signierter Update-Bereich.", 409)
    app = value["titan_version"]
    if not isinstance(app, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", app):
        raise Error("Ungültige Titan-Version im Systemupdate.", 409)
    version(app)
    if not isinstance(value["titan_stage"], str) or value["titan_stage"] not in STAGES:
        raise Error("Ungültiger Titan-Entwicklungsstand im Systemupdate.", 409)
    source = value["titan_source_commit"]
    if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{40}", source):
        raise Error("Ungültiger Titan-Quellstand im Systemupdate.", 409)
    revision = value["system_revision"]
    if type(revision) is not int or not 1 <= revision <= 2**31 - 1:
        raise Error("Ungültige Systemrevision im Update.", 409)
    changes = value.get("package_changes", [])
    if not isinstance(changes, list) or len(changes) > 60:
        raise Error("Ungültige Paketänderungen im Systemupdate.", 409)
    names = set()
    for change in changes:
        if (not isinstance(change, dict) or set(change) != {"name", "old_version", "new_version", "security"}
                or not isinstance(change["name"], str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]{0,127}(?::[a-z0-9_-]{1,32})?", change["name"])
                or change["name"] in names or type(change["security"]) is not bool):
            raise Error("Ungültige Paketänderung im Systemupdate.", 409)
        for field in ("old_version", "new_version"):
            item = change[field]
            if field == "old_version" and item is None:
                continue
            if not isinstance(item, str) or not item or len(item) > 256 or any(ord(char) < 32 for char in item):
                raise Error("Ungültige Paketversion im Systemupdate.", 409)
        names.add(change["name"])
    summary = value.get("security_summary")
    if summary is not None:
        if (not isinstance(summary, dict) or set(summary) != {"total_packages", "security_packages", "checked_at"}
                or type(summary["total_packages"]) is not int or not len(changes) <= summary["total_packages"] <= 100000
                or type(summary["security_packages"]) is not int or not 0 <= summary["security_packages"] <= summary["total_packages"]
                or not isinstance(summary["checked_at"], str)):
            raise Error("Ungültige Sicherheitsübersicht im Systemupdate.", 409)
        from datetime import datetime, timezone
        try:
            checked = datetime.fromisoformat(summary["checked_at"].replace("Z", "+00:00"))
            if checked.tzinfo is None or checked.utcoffset() != timezone.utc.utcoffset(checked):
                raise ValueError("not UTC")
        except (ValueError, OverflowError):
            raise Error("Ungültiger Sicherheitsprüfzeitpunkt im Systemupdate.", 409) from None
        if summary["security_packages"] < sum(change["security"] for change in changes):
            raise Error("Paketänderungen und Sicherheitsübersicht widersprechen sich.", 409)
    return {"release_kind": value["update_kind"], "titan_version": app,
            "titan_stage": value["titan_stage"], "titan_source_commit": source, "system_revision": revision,
            "package_changes": changes, "security_summary": summary}


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


def image_info():
    from . import debian_updates
    return debian_updates.image_info()


def system_status():
    from . import debian_updates
    return debian_updates.system_status()


def check(repo, channel="stable", token=None, update_kind="all"):
    from . import debian_updates
    return debian_updates.check(repo, channel, token, update_kind)


def rollback(repo, expected_digest, confirmation, database):
    from . import debian_updates
    return debian_updates.rollback(repo, expected_digest, confirmation, database)


def reboot(repo, expected_digest, confirmation, database):
    from . import debian_updates
    return debian_updates.reboot(repo, expected_digest, confirmation, database)


def install(repo, channel, expected_version, database, update_kind="all"):
    from . import debian_updates
    return debian_updates.install(repo, channel, expected_version, database, update_kind)
