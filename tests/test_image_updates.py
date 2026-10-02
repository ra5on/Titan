"""Signed image staging without host package installation or automatic reboot."""
from contextlib import ExitStack, closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from titan import updates
from titan.core import Error, Store


REPOSITORY = "ghcr.io/ra5on/titan"
OLD_DIGEST = "sha256:" + "a" * 64
NEW_DIGEST = "sha256:" + "b" * 64
NEW_IMAGE = REPOSITORY + "@" + NEW_DIGEST
INFO = {"format": updates.FORMAT, "platform": "ucore-hci", "version": "0.3.0", "release_stage": "alpha",
        "architecture": "x86_64", "image_repository": REPOSITORY}
MANIFEST = {"format": updates.FORMAT, "platform": "ucore-hci", "version": "0.3.1", "release_stage": "alpha",
            "architecture": "x86_64", "image": NEW_IMAGE, "boot_test": "passed", "runtime_test": "passed"}


def raw_deployment(image, digest, version="0.3.0", incompatible=False):
    return {"image": {"image": {"image": image, "transport": "registry"},
                      "version": version, "imageDigest": digest}, "incompatible": incompatible}


def raw_status(staged=None, booted=None):
    return {"apiVersion": "org.containers.bootc/v1", "kind": "BootcHost",
            "status": {"booted": booted or raw_deployment(REPOSITORY + ":alpha", OLD_DIGEST),
                       "staged": staged, "rollback": None, "rollbackQueued": False}}


class ImageStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.info = Path(self.temp.name) / "image-info.json"
        self.info.write_text(json.dumps(INFO))
        self.addCleanup(patch.stopall)
        patch.object(updates, "IMAGE_INFO", self.info).start()
        patch.object(updates.platform, "machine", return_value="x86_64").start()
        self.command = patch("titan.host.run", return_value=json.dumps(raw_status())).start()

    def test_status_uses_structured_bootc_output_and_does_not_refresh_packages(self):
        result = updates.system_status()
        self.assertEqual(result["current"], "0.3.0")
        self.assertEqual(result["update_kind"], "image")
        self.assertEqual(result["booted"]["digest"], OLD_DIGEST)
        self.assertFalse(result["reboot_required"])
        self.assertFalse(result["automatic_reboot"])
        self.command.assert_called_once_with(["bootc", "status", "--json", "--format-version=1"], timeout=30)

    def test_prepared_image_reports_pending_activation(self):
        self.command.return_value = json.dumps(raw_status(raw_deployment(NEW_IMAGE, NEW_DIGEST, "0.3.1")))
        result = updates.system_status()
        self.assertEqual(result["staged"]["version"], "0.3.1")
        self.assertTrue(result["reboot_required"])
        self.assertEqual(result["current"], "0.3.0")

    def test_scheduled_rollback_also_requires_explicit_restart(self):
        status = raw_status()
        status["status"]["rollbackQueued"] = True
        self.command.return_value = json.dumps(status)
        self.assertTrue(updates.system_status()["reboot_required"])

    def test_non_bootc_host_or_invalid_status_fails_closed(self):
        values = [None, [], {}, {"status": []}, {"status": {"booted": None}},
                  {"status": {"booted": []}}, {"status": {"booted": {"image": None}}}]
        for value in values:
            with self.subTest(value=value):
                self.command.return_value = json.dumps(value)
                with self.assertRaises(Error):
                    updates.system_status()

    def test_unsupported_machine_or_image_architecture_fails_closed(self):
        for machine in ("i686", "aarch64"):
            with self.subTest(machine=machine), patch.object(updates.platform, "machine", return_value=machine), self.assertRaises(Error):
                updates.system_status()
        self.command.assert_not_called()

    def test_missing_immutable_image_record_is_rejected_without_commands(self):
        self.info.unlink()
        with self.assertRaises(Error):
            updates.system_status()
        self.command.assert_not_called()

    def test_duplicate_keys_are_rejected_in_trust_metadata(self):
        self.info.write_text('{"format":"titan-ucore-image-v1","format":"tampered"}')
        with self.assertRaises(Error):
            updates.image_info()

    def test_invalid_registry_digest_or_transport_fails_closed(self):
        for replacement in ({"image": "https://evil.example/image"}, {"transport": "containers-storage"}):
            status = raw_status()
            status["status"]["booted"]["image"]["image"].update(replacement)
            if "image" in replacement:
                status["status"]["booted"]["image"]["imageDigest"] = "bad"
            self.command.return_value = json.dumps(status)
            with self.subTest(replacement=replacement), self.assertRaises(Error):
                updates.system_status()


class ImageInstallTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.info = dict(INFO)
        self.manifest = dict(MANIFEST)
        self.before = {"booted": {"image": REPOSITORY + ":alpha", "digest": OLD_DIGEST, "incompatible": False},
                       "reboot_required": False, "staged": None}
        self.after = {"booted": dict(self.before["booted"]), "reboot_required": True,
                      "staged": {"image": NEW_IMAGE, "digest": NEW_DIGEST, "version": "0.3.1", "incompatible": False}}
        self.release = {"available": True, "signed": True, "latest": "v0.3.1", "latest_stage": "alpha", "assets": {}, "url": "https://github.com/ra5on/Titan"}
        self.stack.enter_context(patch.object(updates, "read_token", return_value=None))
        self.stack.enter_context(patch.object(updates, "check", return_value=self.release))
        self.verified = self.stack.enter_context(patch.object(updates, "verified_release", return_value=(self.manifest, {})))
        self.stack.enter_context(patch.object(updates, "image_info", return_value=self.info))
        self.state = self.stack.enter_context(patch.object(updates, "system_status", side_effect=[self.before, self.after]))
        self.policy = self.stack.enter_context(patch.object(updates, "verify_container_policy"))
        self.backup = self.stack.enter_context(patch.object(updates, "backup_configuration", return_value="/backup/config.sqlite3"))
        self.command = self.stack.enter_context(patch("titan.host.run", return_value=""))

    def install(self, channel="alpha"):
        return updates.install("ra5on/Titan", channel, "v0.3.1", "/config/titan.sqlite3")

    def assert_no_mutation(self):
        self.command.assert_not_called()
        self.backup.assert_not_called()

    def test_verified_image_is_staged_without_restart_and_result_explains_activation(self):
        result = self.install()
        self.assertTrue(result["ok"])
        self.assertTrue(result["reboot_required"])
        self.assertFalse(result["automatic_reboot"])
        self.command.assert_called_once_with(["bootc", "switch", "--enforce-container-sigpolicy", NEW_IMAGE], timeout=1800)
        self.backup.assert_called_once_with("/config/titan.sqlite3")
        self.assertEqual(result["staged"]["digest"], NEW_DIGEST)
        self.verified.assert_called_once()

    def test_signature_channel_and_exact_version_checked_before_mutation(self):
        self.manifest["version"] = "0.3.2"
        with self.assertRaises(Error):
            self.install()
        self.assert_no_mutation()

    def test_manifest_cannot_select_another_image_repository_or_mutable_tag(self):
        references = [REPOSITORY + ":alpha", "ghcr.io/attacker/titan@" + NEW_DIGEST,
                      REPOSITORY + "@sha256:short", NEW_IMAGE.upper(), "docker://" + NEW_IMAGE,
                      NEW_IMAGE + "; reboot", "https://ghcr.io/ra5on/titan@" + NEW_DIGEST]
        for reference in references:
            self.manifest["image"] = reference
            with self.subTest(reference=reference), self.assertRaises(Error):
                self.install()
            self.assert_no_mutation()

    def test_manifest_must_explicitly_identify_image_format_platform_stage_and_architecture(self):
        for key, value in (("format", "unsupported"), ("platform", "unsupported"), ("architecture", "aarch64"),
                           ("release_stage", []), ("release_stage", None)):
            self.manifest.clear()
            self.manifest.update(MANIFEST)
            self.manifest[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(Error):
                self.install()
            self.assert_no_mutation()

    def test_missing_or_unknown_verification_cannot_reach_image_staging(self):
        for field in ('boot_test', 'runtime_test'):
            for status in ('failed', 'not-run', 'unknown', None):
                self.manifest.clear()
                self.manifest.update(MANIFEST)
                self.manifest[field] = status
                with self.subTest(field=field, status=status), self.assertRaises(Error) as result:
                    self.install()
                self.assertEqual(result.exception.status, 409)
                self.assert_no_mutation()
            self.manifest.clear()
            self.manifest.update(MANIFEST)
            del self.manifest[field]
            with self.subTest(field=field, missing=True), self.assertRaises(Error):
                self.install()
            self.assert_no_mutation()

    def test_queued_update_rechecks_installed_version_and_pending_state(self):
        self.info["version"] = "0.3.2"
        with self.assertRaises(Error):
            self.install()
        self.assert_no_mutation()

    def test_pending_deployment_is_not_overwritten(self):
        self.before["reboot_required"] = True
        with self.assertRaises(Error) as raised:
            self.install()
        self.assertEqual(raised.exception.status, 409)
        self.assert_no_mutation()

    def test_local_package_layering_is_not_supported(self):
        self.before["booted"]["incompatible"] = True
        with self.assertRaises(Error):
            self.install()
        self.assert_no_mutation()

    def test_wrong_booted_repository_is_not_rebased(self):
        self.before["booted"]["image"] = "ghcr.io/ublue-os/ucore-hci:stable"
        with self.assertRaises(Error):
            self.install()
        self.assert_no_mutation()

    def test_already_booted_digest_is_not_reinstalled(self):
        self.before["booted"]["digest"] = NEW_DIGEST
        with self.assertRaises(Error):
            self.install()
        self.assert_no_mutation()

    def test_relaxed_signature_policy_cannot_start_image_download(self):
        self.policy.side_effect = Error("Policy rejects signature")
        with self.assertRaises(Error):
            self.install()
        self.assert_no_mutation()

    def test_backup_failure_prevents_image_switch(self):
        self.backup.side_effect = sqlite3.DatabaseError("configuration unavailable")
        with self.assertRaises(sqlite3.DatabaseError):
            self.install()
        self.command.assert_not_called()

    def test_process_failure_cannot_be_reported_as_success(self):
        self.command.side_effect = Error("Image signature was required")
        with self.assertRaises(Error):
            self.install()
        self.state.assert_called_once()

    def test_successful_command_must_have_staged_exact_digest_version_and_reference(self):
        for key, value in (("digest", OLD_DIGEST), ("version", "0.3.9"), ("image", REPOSITORY + ":alpha"), ("incompatible", True)):
            after = {**self.after, "staged": {**self.after["staged"], key: value}}
            self.state.side_effect = [self.before, after]
            with self.subTest(key=key), self.assertRaises(Error):
                self.install()


class ContainerTrustTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.policy, self.key, self.public = (directory / name for name in ("policy.json", "container.pub", "release.pem"))
        self.key.write_text("trusted public key\n")
        self.public.write_text("trusted public key\n")
        self.rule = {"type": "sigstoreSigned", "keyPath": str(self.key), "signedIdentity": {"type": "matchRepository"}}
        self.value = {"default": [{"type": "reject"}], "transports": {"docker": {REPOSITORY: [self.rule]}}}
        self.addCleanup(patch.stopall)
        patch.object(updates, "CONTAINER_POLICY", self.policy).start()
        patch.object(updates, "CONTAINER_KEY", self.key).start()
        patch.object(updates, "PUBLIC_KEY", self.public).start()

    def verify(self):
        self.policy.write_text(json.dumps(self.value))
        return updates.verify_container_policy(INFO)

    def test_repository_requires_exact_release_signing_key(self):
        self.verify()
        self.public.write_text("different publisher")
        with self.assertRaises(Error):
            self.verify()

    def test_unsigned_or_wrong_scope_or_relaxed_identity_is_rejected(self):
        for field, value in (("type", "insecureAcceptAnything"), ("keyPath", "/untrusted.pub"),
                             ("signedIdentity", {"type": "matchExact"}), ("signedIdentity", None)):
            original = dict(self.rule)
            self.rule[field] = value
            with self.subTest(field=field), self.assertRaises(Error):
                self.verify()
            self.rule.clear()
            self.rule.update(original)
        self.value["transports"]["docker"] = {"ghcr.io/ra5on": [self.rule]}
        with self.assertRaises(Error):
            self.verify()

    def test_missing_key_fails_closed(self):
        self.key.unlink()
        with self.assertRaises(Error):
            self.verify()

    def test_multiple_or_empty_requirement_list_is_rejected(self):
        for rules in ([], [self.rule, {"type": "insecureAcceptAnything"}], None):
            self.value["transports"]["docker"][REPOSITORY] = rules
            with self.subTest(rules=rules), self.assertRaises(Error):
                self.verify()

    def test_default_accept_and_more_specific_signature_bypass_are_rejected(self):
        self.value["default"] = [{"type": "insecureAcceptAnything"}]
        with self.assertRaises(Error):
            self.verify()
        self.value["default"] = [{"type": "reject"}]
        self.value["transports"]["docker"][NEW_IMAGE] = [{"type": "insecureAcceptAnything"}]
        with self.assertRaises(Error):
            self.verify()


class ConfigurationSafetyTests(unittest.TestCase):
    def test_backup_is_consistent_readable_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database = directory / "source.sqlite3"
            with closing(sqlite3.connect(database)) as source:
                source.execute("CREATE TABLE settings(value TEXT)")
                source.execute("INSERT INTO settings VALUES (?)", ("preserved",))
                source.commit()
            with patch.object(updates, "BACKUP_DIRECTORY", directory / "backups"):
                backup = Path(updates.backup_configuration(database))
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            with closing(sqlite3.connect(backup)) as connection:
                self.assertEqual(connection.execute("SELECT value FROM settings").fetchone()[0], "preserved")

    def test_missing_source_database_is_not_silently_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "missing.sqlite3"
            with patch.object(updates, "BACKUP_DIRECTORY", directory / "backups"), self.assertRaises(sqlite3.OperationalError):
                updates.backup_configuration(source)
            self.assertFalse(source.exists())

    def test_automatic_reboot_cannot_be_enabled_and_legacy_setting_is_sanitized(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            store.set_config("settings", {"allow_reboot": True})
            self.assertFalse(store.settings()["allow_reboot"])
            with self.assertRaises(Error):
                store.save_settings({"allow_reboot": True})
            self.assertFalse(store.save_settings({"installation": "automatic"})["allow_reboot"])


if __name__ == "__main__":
    unittest.main()
