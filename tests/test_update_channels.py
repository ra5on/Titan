"""Update channels and authenticated immutable image staging boundaries."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from titan.core import Error
from titan.server import Application, Handler
from titan import updates, debian_updates
from update_fixtures import identity, manifest, state


def release(tag, *, name=None, prerelease=False, draft=False):
    value = {"tag_name": tag, "name": name or tag, "prerelease": prerelease,
             "draft": draft, "body": "Release notes", "html_url": "https://github.com/example/titan/releases/" + tag,
             "assets": [{"name": "manifest.json", "url": "https://api.github.com/assets/" + tag + "/manifest"},
                        {"name": "manifest.json.sig", "url": "https://api.github.com/assets/" + tag + "/signature"},
                        {"name":"titan-test-amd64.raucb","url":"https://api.github.com/assets/bundle"}]}
    return value


class ChannelSelectionTests(unittest.TestCase):
    def check(self, releases, channel, current="0.0.0"):
        info = identity(current)
        status = state(current)
        def download(url, *args, **kwargs):
            if "/releases?" in url:
                return json.dumps(releases).encode()
            tag = url.split("/")[-2]
            item = next(item for item in releases if isinstance(item, dict) and item.get("tag_name") == tag)
            return json.dumps(manifest(tag, updates.release_stage(item))).encode()
        with ExitStack() as stack:
            stack.enter_context(patch.object(updates, "__version__", current))
            stack.enter_context(patch.object(debian_updates, "image_info", return_value=info))
            stack.enter_context(patch.object(debian_updates, "system_status", return_value=status))
            stack.enter_context(patch.object(updates, "PUBLIC_KEY", Mock(is_file=Mock(return_value=True))))
            stack.enter_context(patch.object(updates, "fetch", side_effect=download))
            stack.enter_context(patch.object(updates, "verify_manifest", side_effect=lambda path, *args: updates.strict_json(Path(path).read_bytes())))
            return updates.check("example/titan", channel)

    def test_same_version_progresses_from_alpha_to_beta_to_stable(self):
        tags = ["v1.2.0-alpha.1", "v1.2.0-alpha.10", "v1.2.0-beta.1", "v1.2.0-beta.10", "v1.2.0"]
        parsed = [updates.version(tag) for tag in tags]
        self.assertEqual(parsed, sorted(parsed))
        self.assertEqual(len(set(parsed)), len(tags))
        self.assertGreater(updates.version("1.3.0-alpha.1"), updates.version("1.2.0"))

    def test_bare_alpha_current_can_update_to_beta_and_stable_of_same_version(self):
        releases = [release("v1.0.0", name="Titan 1.0.0 Stable")]
        result = self.check(releases, "stable", current="1.0.0")
        self.assertTrue(result["available"])
        self.assertEqual(result["latest_stage"], "stable")
        releases = [release("v1.0.0", name="Titan 1.0.0 Alpha", prerelease=True),
                    release("v1.0.0-beta.1", prerelease=True)]
        result = self.check(releases, "alpha", current="1.0.0")
        self.assertEqual(result["latest"], "v1.0.0-beta.1")
        self.assertTrue(result["available"])

    def test_unsupported_or_malformed_versions_are_rejected(self):
        for tag in ("v1.2", "v1.2.0-rc.1", "v1.2.0-alpha", "v1.2.0-beta.-1", "v1.2.0-alpha.1.extra", "v1.2.0+build"):
            with self.subTest(tag=tag), self.assertRaises(Error):
                updates.version(tag)

    def test_channels_include_only_their_permitted_release_stages(self):
        releases = [release("v1.0.0"), release("v1.1.0-beta.1", prerelease=True),
                    release("v1.2.0-alpha.1", prerelease=True)]
        for channel, expected in (("stable", "v1.0.0"), ("beta", "v1.1.0-beta.1"), ("alpha", "v1.2.0-alpha.1")):
            with self.subTest(channel=channel):
                result = self.check(releases, channel)
                self.assertEqual(result.get("latest"), expected)
                self.assertTrue(result["available"])

    def test_beta_and_alpha_channels_also_accept_final_stable_release(self):
        releases = [release("v1.0.0-beta.10", prerelease=True), release("v1.0.0")]
        for channel in ("alpha", "beta", "stable"):
            with self.subTest(channel=channel):
                self.assertEqual(self.check(releases, channel)["latest"], "v1.0.0")

    def test_legacy_alpha_releases_are_excluded_from_beta_and_stable(self):
        releases = [release("v0.1.0", name="Titan 0.1.0 Alpha"),
                    release("v0.2.0", name="Titan 0.2.0 Alpha")]
        for channel in ("beta", "stable"):
            with self.subTest(channel=channel):
                result = self.check(releases, channel)
                self.assertFalse(result["available"])
                self.assertNotIn("latest", result)
        self.assertEqual(self.check(releases, "alpha")["latest"], "v0.2.0")

    def test_explicit_titles_classify_bare_prerelease_tags(self):
        releases = [release("v1.1.0", name="Titan 1.1.0 Alpha", prerelease=True),
                    release("v1.0.0", name="Titan 1.0.0 Beta", prerelease=True)]
        self.assertEqual(self.check(releases, "beta")["latest"], "v1.0.0")
        self.assertEqual(self.check(releases, "alpha")["latest"], "v1.1.0")
        self.assertFalse(self.check(releases, "stable")["available"])

    def test_prerelease_flag_cannot_promote_unknown_tag_to_stable_or_beta(self):
        item = release("v1.0.0", name="Preview release", prerelease=True)
        for channel in ("stable", "beta"):
            with self.subTest(channel=channel):
                self.assertFalse(self.check([item], channel)["available"])
        self.assertEqual(self.check([item], "alpha")["latest"], "v1.0.0")

    def test_missing_prerelease_flag_does_not_promote_tag_or_title(self):
        for item in (release("v1.0.0-alpha.1"), release("v1.0.0-beta.1"),
                     release("v1.0.0", name="Titan Beta"), release("v1.0.0", name="Titan Alpha")):
            with self.subTest(item=item):
                self.assertFalse(self.check([item], "stable")["available"])

    def test_conflicting_or_ambiguous_stage_signals_are_skipped(self):
        for item in (release("v1.0.0-alpha.1", name="Titan Beta", prerelease=True),
                     release("v1.0.0-beta.1", name="Titan Alpha", prerelease=True),
                     release("v1.0.0", name="Titan Alpha and Beta", prerelease=True)):
            with self.subTest(item=item):
                with self.assertRaises(Error):
                    updates.release_stage(item)
                for channel in ("stable", "beta", "alpha"):
                    self.assertFalse(self.check([item], channel)["available"])

    def test_stable_title_cannot_override_prerelease_flag(self):
        item = release("v1.0.0", name="Titan Stable", prerelease=True)
        for channel in ("stable", "beta", "alpha"):
            with self.subTest(channel=channel):
                self.assertFalse(self.check([item], channel)["available"])

    def test_allowed_stage_matrix(self):
        permitted = {"stable": {"stable"}, "beta": {"stable", "beta"}, "alpha": {"stable", "beta", "alpha"}}
        for channel, stages in permitted.items():
            for stage in ("alpha", "beta", "stable"):
                with self.subTest(channel=channel, stage=stage):
                    self.assertEqual(updates.allowed_stage(channel, stage), stage in stages)

    def test_drafts_and_invalid_versions_never_become_candidates(self):
        releases = [release("v9.0.0", draft=True), release("v10.0.0-rc.1"), release("v1.0.0")]
        self.assertEqual(self.check(releases, "alpha")["latest"], "v1.0.0")

    def test_channel_switch_does_not_offer_a_downgrade(self):
        result = self.check([release("v1.0.0")], "stable", current="1.1.0-alpha.1")
        self.assertEqual(result["latest"], "v1.0.0")
        self.assertFalse(result["available"])

    def test_invalid_channel_is_rejected_before_network_access(self):
        with patch.object(updates, "fetch") as fetch, self.assertRaises(Error):
            updates.check("example/titan", "nightly")
        fetch.assert_not_called()

    def test_malformed_json_or_non_list_github_response_returns_structured_error(self):
        for payload in (b"not json", b'"release"', b'{"message":"unexpected"}', b"null", b"\xff"):
            with self.subTest(payload=payload), patch.object(updates, "fetch", return_value=payload):
                result = updates.check("example/titan", "alpha")
                self.assertFalse(result["available"])
                self.assertIn("error", result)
                self.assertNotIn("latest", result)

    def test_invalid_github_entries_do_not_hide_valid_releases(self):
        invalid = [None, "release", [], {"tag_name": "v" + "9" * 5000 + ".0.0"},
                   {"tag_name": "v9.0.0", "name": ["stable"]}, {"tag_name": "v9.0.0", "draft": "false"}]
        self.assertEqual(self.check([*invalid, release("v1.0.0")], "stable")["latest"], "v1.0.0")

    def test_malformed_release_assets_return_structured_error(self):
        for assets in (None, {}, [None], [{"name": "manifest.json"}], [{"name": "manifest.json", "url": []}]):
            item = release("v1.0.0")
            item["assets"] = assets
            with self.subTest(assets=assets):
                result = self.check([item], "stable")
                self.assertFalse(result["available"])
                self.assertIn("error", result)


class ImageStagingReached(Exception):
    """Stop before the only privileged image mutation."""


class ManifestChannelTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.events = []
        self.info = identity()
        self.manifest = manifest('1.0.0','stable')
        self.release = {"available": True, "latest": "v1.0.0", "latest_stage": "stable", "signed": True,
                        "url": "https://github.com/example/titan/releases/v1.0.0",
                        "assets": {"manifest.json": "https://api.github.com/assets/manifest",
                                   "manifest.json.sig": "https://api.github.com/assets/signature"}}
        self.state = state()
        self.stack.enter_context(patch.object(updates, "read_token", return_value=None))
        self.stack.enter_context(patch.object(debian_updates, "check", side_effect=self.offer))
        self.stack.enter_context(patch.object(debian_updates, "image_info", return_value=self.info))
        self.stack.enter_context(patch.object(debian_updates, "system_status", return_value=self.state))
        self.stack.enter_context(patch.object(updates, "PUBLIC_KEY", Mock(is_file=Mock(return_value=True))))
        self.backup = self.stack.enter_context(patch.object(updates, "backup_configuration", side_effect=ImageStagingReached))
        self.run = self.stack.enter_context(patch("titan.host.run", side_effect=ImageStagingReached))
        self.fetch = self.stack.enter_context(patch.object(updates, "fetch", side_effect=self.download))
        self.verify = self.stack.enter_context(patch.object(updates, "verify_manifest", side_effect=self.verified_manifest))

    def offer(self,*args):
        updates.version(self.info['version'])
        return {**self.release,'available':updates.staged_version(self.release['latest'],self.release['latest_stage'])>updates.staged_version(self.info['version'],self.info['release_stage'])}

    def download(self, url, *args, **kwargs):
        self.events.append("signature" if url.endswith("/signature") else "manifest")
        return b"signature" if url.endswith("/signature") else json.dumps(self.manifest).encode()

    def verified_manifest(self, *args):
        self.events.append("verify")
        return self.manifest.copy()

    def install(self, channel):
        return debian_updates.install.__wrapped__.__wrapped__("example/titan", channel, self.release["latest"], "/unused/database.sqlite3")

    def assert_rejected_before_staging(self, channel):
        with self.assertRaises(Error):
            self.install(channel)
        self.assertEqual(self.events, ["manifest", "signature", "verify"])
        self.run.assert_not_called()
        self.backup.assert_not_called()

    def test_signed_alpha_manifest_cannot_be_installed_on_beta_or_stable(self):
        self.manifest["release_stage"] = "alpha"
        for channel in ("beta", "stable"):
            with self.subTest(channel=channel):
                self.events.clear()
                self.assert_rejected_before_staging(channel)

    def test_signed_stage_must_match_github_release_metadata(self):
        self.manifest["release_stage"] = "beta"
        self.assert_rejected_before_staging("alpha")

    def test_unmarked_manifests_are_conservatively_alpha(self):
        self.manifest.pop("release_stage")
        for channel in ("stable", "beta"):
            with self.subTest(channel=channel):
                self.events.clear()
                self.assert_rejected_before_staging(channel)

    def test_explicit_signed_stage_cannot_promote_prerelease_suffix(self):
        for version, stage in (("1.0.0-alpha.1", "beta"), ("1.0.0-alpha.1", "stable"),
                               ("1.0.0-beta.1", "stable")):
            with self.subTest(version=version, stage=stage), self.assertRaises(Error):
                updates.manifest_stage({"version": version, "release_stage": stage})

    def test_unknown_signed_stage_is_rejected(self):
        for stage in ("preview", "Beta", None, False, ["stable"]):
            with self.subTest(stage=stage), self.assertRaises(Error):
                updates.manifest_stage({"version": "1.0.0", "release_stage": stage})

    def test_manifest_suffix_remains_a_trusted_stage_after_signature(self):
        for version, stage in (("1.0.0-alpha.1", "alpha"), ("1.0.0-beta.1", "beta")):
            with self.subTest(version=version):
                self.assertEqual(updates.manifest_stage({"version": version}), stage)

    def test_allowed_authenticated_manifest_reaches_staging_only_after_signature(self):
        for stage, channels in (("alpha", ("alpha",)), ("beta", ("alpha", "beta")),
                                ("stable", ("alpha", "beta", "stable"))):
            self.manifest["release_stage"] = self.release["latest_stage"] = stage
            for channel in channels:
                with self.subTest(stage=stage, channel=channel):
                    self.events.clear()
                    with self.assertRaises(ImageStagingReached):
                        self.install(channel)
                    self.assertEqual(self.events, ["manifest", "signature", "verify"])
        self.assertEqual(self.backup.call_count, 6)
        self.run.assert_not_called()

    def test_running_old_agent_cannot_stage_a_downgrade(self):
        self.info["version"] = "1.1.0-alpha.1"
        with patch.object(updates, "__version__", "0.2.1"), self.assertRaises(Error) as raised:
            self.install("stable")
        self.assertEqual(raised.exception.status, 409)
        self.run.assert_not_called()

    def test_already_started_version_is_not_reinstalled(self):
        self.info["version"] = "1.0.0"
        self.info["release_stage"] = "stable"
        with self.assertRaises(Error) as raised:
            self.install("stable")
        self.assertEqual(raised.exception.status, 409)
        self.run.assert_not_called()

    def test_alpha_and_beta_versions_follow_semver_order(self):
        for installed in ("1.0.0-alpha.10", "1.0.0-beta.10"):
            self.info["version"] = installed
            self.info["release_stage"] = "alpha" if "alpha" in installed else "beta"
            with self.subTest(installed=installed):
                with self.assertRaises(ImageStagingReached):
                    self.install("stable")

    def test_unknown_installed_image_version_fails_before_staging(self):
        self.info["version"] = "invalid-version"
        with self.assertRaises(Error):
            self.install("stable")
        self.run.assert_not_called()

    def test_bad_signature_stops_before_manifest_stage_and_image_mutation(self):
        self.verify.side_effect = Error("Ungültige Signatur.")
        with patch.object(updates, "manifest_stage", wraps=updates.manifest_stage) as classify, self.assertRaises(Error):
            self.install("stable")
        classify.assert_not_called()
        self.assertEqual(self.events, ["manifest", "signature"])
        self.run.assert_not_called()

    def test_legacy_package_manifest_is_rejected(self):
        self.manifest = {"version": "1.0.0", "release_stage": "stable", "package_name": "titan",
                         "format": "legacy-package-v1", "asset": "titan_1.0.0.tar", "sha256": "a" * 64}
        self.assert_rejected_before_staging("stable")


class QueuedJobs:
    def __init__(self):
        self.pending = []

    def submit(self, actor, operation, function, **kwargs):
        self.pending.append(function)
        return {"job": "queued-test-job"}


class ChannelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Application(self.temp.name, demo=True)
        self.addCleanup(self.app.agent._temporary.cleanup)
        self.app.agent = Mock()
        self.app.agent.call.return_value = {"ok": True}
        self.app.jobs = QueuedJobs()

    def test_all_three_channels_can_be_saved_and_unknown_channel_is_rejected(self):
        for channel in ("alpha", "beta", "stable"):
            with self.subTest(channel=channel):
                self.assertEqual(self.app.save_settings({"channel": channel})["channel"], channel)
        with self.assertRaises(Error):
            self.app.save_settings({"channel": "nightly"})

    def test_repository_or_channel_change_invalidates_cached_offer(self):
        for change in ({"channel": "beta"}, {"repository": "example/titan"}):
            self.app.store.set_config("update", {"available": True, "latest": "v9.0.0", "checked": 123,
                "repository": self.app.store.settings()["repository"], "channel": self.app.store.settings()["channel"]})
            with self.subTest(change=change):
                settings = self.app.save_settings(change)
                cached = self.app.store.config("update", {})
                self.assertFalse(cached["available"])
                self.assertNotIn("latest", cached)
                self.assertEqual(cached["channel"], settings["channel"])
                self.assertEqual(cached["repository"], settings["repository"])

    def test_unrelated_setting_does_not_invalidate_cached_offer(self):
        cached = {"available": True, "latest": "v9.0.0", "checked": 123}
        self.app.store.set_config("update", cached)
        self.app.save_settings({"hostname": "New NAS"})
        self.assertEqual(self.app.store.config("update", {}), cached)

    def test_queued_manual_install_uses_current_channel_and_repository(self):
        self.app.save_settings({"channel": "alpha"})
        captured = {"repository": "ra5on/Titan", "channel": "alpha", "expected_version": "v1.0.0-alpha.1"}
        self.app.jobs.submit("demo", "update_install", lambda: self.app.admin_action("demo", "update_install", captured))
        self.app.save_settings({"channel": "stable", "repository": "example/titan"})
        self.app.jobs.pending.pop()()
        self.app.agent.call.assert_called_once_with("update_install", repository="example/titan", channel="stable",
                                                   expected_version="v1.0.0-alpha.1")

    def test_queued_update_check_uses_current_settings(self):
        self.app.save_settings({"channel": "alpha"})
        self.app.jobs.submit("demo", "update_check", self.app.update_check)
        self.app.save_settings({"channel": "beta"})
        self.app.jobs.pending.pop()()
        self.app.agent.call.assert_called_once_with("update_check", repository="ra5on/Titan", channel="beta")

    def test_queued_automatic_install_rechecks_mode_and_channel(self):
        self.app.save_settings({"channel": "alpha", "installation": "automatic"})
        queued = lambda: self.app.install_update("system", "v1.0.0-alpha.1", automatic=True)
        self.app.save_settings({"channel": "beta"})
        now = SimpleNamespace(tm_wday=6, tm_hour=3)
        with patch("titan.server.time.localtime", return_value=now):
            queued()
        self.app.agent.call.assert_called_once_with("update_install", repository="ra5on/Titan", channel="beta",
                                                   expected_version="v1.0.0-alpha.1")
        self.app.agent.call.reset_mock()
        self.app.save_settings({"installation": "manual"})
        with self.assertRaises(Error):
            queued()
        self.app.agent.call.assert_not_called()

    def test_queued_install_rechecks_admin_permission(self):
        self.app.store.create_user("second", "second-long-password", "admin", "second")
        self.app.store.update_user("demo", role="user")
        with self.assertRaises(Error):
            self.app.admin_action("demo", "update_install", {"expected_version": "v1.0.0"})
        self.app.agent.call.assert_not_called()

    def test_actual_automatic_queue_uses_settings_at_execution(self):
        self.app.demo = False
        self.app.save_settings({"channel": "alpha", "installation": "automatic", "auto_check": False})
        self.app.store.set_config("update", {"available": True, "signed": True, "latest": "v1.0.0-alpha.1"})
        self.app.stop = Mock()
        self.app.stop.wait.side_effect = [False, True]
        now = SimpleNamespace(tm_year=2026, tm_yday=273, tm_wday=6, tm_hour=3)
        with patch("titan.server.time.localtime", return_value=now):
            self.app.updater()
        self.assertEqual(len(self.app.jobs.pending), 1)
        self.app.save_settings({"channel": "stable", "repository": "example/titan"})
        with patch("titan.server.time.localtime", return_value=now):
            self.app.jobs.pending.pop()()
        self.app.agent.call.assert_called_once_with("update_install", repository="example/titan", channel="stable",
                                                   expected_version="v1.0.0-alpha.1")

    def test_inflight_old_channel_check_cannot_overwrite_completed_settings_change(self):
        self.app.save_settings({"channel": "alpha"})
        entered, release_check, settings_attempted = threading.Event(), threading.Event(), threading.Event()
        original_lock = self.app.update_lock
        errors = []

        class ObservedLock:
            def __enter__(self):
                if threading.current_thread().name == "settings-change":
                    settings_attempted.set()
                original_lock.acquire()

            def __exit__(self, *args):
                original_lock.release()

        def old_check(*args, **kwargs):
            entered.set()
            if not release_check.wait(3):
                raise AssertionError("Test did not release old-channel update check")
            return {"available": True, "latest": "v9.0.0-alpha.1", "channel": "alpha", "repository": "ra5on/Titan"}

        def worker(function):
            try:
                function()
            except Exception as exc:
                errors.append(exc)

        self.app.update_lock = ObservedLock()
        self.app.agent.call.side_effect = old_check
        checker = threading.Thread(target=worker, args=(self.app.update_check,), name="old-check")
        saver = threading.Thread(target=worker, args=(lambda: self.app.save_settings({"channel": "beta"}),), name="settings-change")
        checker.start()
        try:
            self.assertTrue(entered.wait(2))
            saver.start()
            self.assertTrue(settings_attempted.wait(2))
        finally:
            release_check.set()
            checker.join(3)
            if saver.ident is not None:
                saver.join(3)
        self.assertFalse(checker.is_alive())
        self.assertFalse(saver.is_alive())
        self.assertEqual(errors, [])
        cached = self.app.store.config("update", {})
        self.assertFalse(cached["available"])
        self.assertEqual(cached["channel"], "beta")
        self.assertNotIn("latest", cached)

    def test_api_settings_change_invalidates_offer_and_queued_install_uses_new_channel(self):
        self.app.save_settings({"channel": "alpha"})
        self.app.store.set_config("update", {"available": True, "latest": "v1.0.0-alpha.1"})
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(app=self.app)
        handler.headers = {"X-CSRF-Token": "demo-only"}

        def request(path, body=None):
            handler.path = path
            handler.body = Mock(return_value=body)
            handler.reply = Mock()
            (handler.get if body is None else handler.post)()
            arguments = handler.reply.call_args.args
            return (arguments[1] if len(arguments) > 1 else 200), arguments[0]

        status, _ = request("/api/actions", {"operation": "update_install", "arguments": {"expected_version": "v1.0.0-alpha.1"}})
        self.assertEqual(status, 202)
        self.assertEqual(request("/api/settings", {"channel": "stable"})[0], 200)
        cached = request("/api/updates")[1]
        self.assertFalse(cached["available"])
        self.assertEqual(cached["channel"], "stable")
        self.app.jobs.pending.pop()()
        self.app.agent.call.assert_called_once_with("update_install", repository="ra5on/Titan", channel="stable",
                                                   expected_version="v1.0.0-alpha.1")


if __name__ == "__main__":
    unittest.main()
