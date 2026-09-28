from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import updater


class FakeResponse(io.BytesIO):
    status = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class UpdaterTests(unittest.TestCase):
    def test_semver_accepts_only_stable_three_part_versions(self):
        self.assertEqual(updater._version_tuple("v1.12.3"), (1, 12, 3))
        self.assertIsNone(updater._version_tuple("v1.2"))
        self.assertIsNone(updater._version_tuple("v1.2.3-beta"))

    def test_download_checks_sha256(self):
        payload = b"signed-by-publisher-over-https"
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "app.exe"
            with patch.object(updater.urllib.request, "urlopen", return_value=FakeResponse(payload)):
                updater._download("https://github.com/owner/repo/app.exe", target, expected)
            self.assertEqual(target.read_bytes(), payload)

    def test_download_deletes_file_when_hash_does_not_match(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "app.exe"
            with patch.object(updater.urllib.request, "urlopen", return_value=FakeResponse(b"tampered")):
                with self.assertRaisesRegex(OSError, "SHA-256"):
                    updater._download("https://github.com/owner/repo/app.exe", target, "0" * 64)
            self.assertFalse(target.exists())

    def test_current_release_does_not_trigger_update(self):
        with patch.object(updater.sys, "frozen", True, create=True), patch.object(
            updater, "_fetch_json", return_value={"tag_name": "v1.0.0", "assets": []}
        ), patch.object(updater, "_apply_from_helper") as apply:
            self.assertFalse(updater.check_and_apply_update())
        apply.assert_not_called()

    def test_new_release_is_downloaded_and_scheduled_for_update(self):
        content = b"new-app-binary"
        release = {
            "tag_name": "v999.0.0",
            "draft": False,
            "prerelease": False,
            "assets": [{
                "name": updater.RELEASE_ASSET_NAME,
                "browser_download_url": "https://github.com/owner/repo/download/app.exe",
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / updater.RELEASE_ASSET_NAME
            executable.write_bytes(b"old-app")
            with patch.object(updater.sys, "frozen", True, create=True), patch.object(
                updater.sys, "platform", "win32"
            ), patch.object(updater.sys, "executable", str(executable)), patch.object(
                updater, "_fetch_json", return_value=release
            ), patch.object(updater.urllib.request, "urlopen", return_value=FakeResponse(content)), patch.object(
                updater, "_apply_from_helper"
            ) as apply:
                self.assertTrue(updater.check_and_apply_update())
            apply.assert_called_once()
            staged_path = Path(apply.call_args.args[0])
            self.assertEqual(staged_path.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
