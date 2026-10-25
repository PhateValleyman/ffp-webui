import hashlib
import importlib.machinery
import importlib.util
import os
import stat
import tempfile
import unittest
from unittest import mock


MODULE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp_webui_update.py')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_update_test_module', MODULE_PATH)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
UPDATES = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(UPDATES)


class FakeResponse:
    def __init__(self, status=200, data=b'', headers=None):
        self.status = status
        self.data = data
        self.headers = headers or {}
        self.offset = 0

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, size=-1):
        if size < 0:
            size = len(self.data) - self.offset
        result = self.data[self.offset:self.offset + size]
        self.offset += len(result)
        return result

    def close(self):
        pass


class FakeConnection:
    def close(self):
        pass


class GitHubUpdateTests(unittest.TestCase):
    def release(self, version='1.10.0', **overrides):
        tag = 'v' + version
        filename = 'ffp-webui-' + version + '-python3.13-static-UNVERIFIED.txz'
        digest = hashlib.sha256(b'package').hexdigest()
        document = {
            'tag_name': tag,
            'draft': False,
            'prerelease': False,
            'html_url': 'https://github.com/PhateValleyman/ffp-webui/releases/tag/' + tag,
            'published_at': '2026-10-25T00:00:00Z',
            'body': 'Release notes',
            'assets': [{
                'name': filename,
                'state': 'uploaded',
                'digest': 'sha256:' + digest,
                'size': len(b'package'),
                'browser_download_url': 'https://github.com/PhateValleyman/ffp-webui/releases/download/' + tag + '/' + filename,
            }],
        }
        document.update(overrides)
        return document

    def test_parses_valid_stable_release_and_compares_semver(self):
        result = UPDATES.parse_release(self.release('1.10.0'), '1.9.9')
        self.assertTrue(result['newer'])
        self.assertEqual(result['version'], '1.10.0')
        self.assertEqual(result['asset_name'], 'ffp-webui-1.10.0-python3.13-static-UNVERIFIED.txz')
        self.assertEqual(result['sha256'], hashlib.sha256(b'package').hexdigest())
        self.assertEqual(result['release_url'], 'https://github.com/PhateValleyman/ffp-webui/releases/tag/v1.10.0')
        self.assertFalse(UPDATES.parse_release(self.release('1.9.9'), '1.10.0')['newer'])

    def test_rejects_prerelease_draft_and_non_semver_tags(self):
        with self.assertRaisesRegex(ValueError, 'stable'):
            UPDATES.parse_release(self.release('1.10.0', prerelease=True), '1.9.9')
        with self.assertRaisesRegex(ValueError, 'stable'):
            UPDATES.parse_release(self.release('1.10.0', draft=True), '1.9.9')
        with self.assertRaisesRegex(ValueError, 'stable'):
            UPDATES.parse_release(self.release('1.10.0-rc.1'), '1.9.9')

    def test_rejects_missing_digest_unexpected_asset_and_untrusted_url(self):
        no_digest = self.release('1.10.0')
        no_digest['assets'][0]['digest'] = None
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            UPDATES.parse_release(no_digest, '1.9.9')

        wrong_url = self.release('1.10.0')
        wrong_url['assets'][0]['browser_download_url'] = 'https://example.org/package.txz'
        with self.assertRaisesRegex(ValueError, 'URL'):
            UPDATES.parse_release(wrong_url, '1.9.9')

        wrong_asset = self.release('1.10.0')
        wrong_asset['assets'][0]['name'] = 'another-project.txz'
        with self.assertRaisesRegex(ValueError, 'installer'):
            UPDATES.parse_release(wrong_asset, '1.9.9')

        incomplete = self.release('1.10.0')
        incomplete['assets'][0]['state'] = 'new'
        with self.assertRaisesRegex(ValueError, 'fully uploaded'):
            UPDATES.parse_release(incomplete, '1.9.9')

    def test_stages_only_matching_verified_content_with_private_permissions(self):
        content = b'package'
        record = {
            'asset_url': 'https://github.com/PhateValleyman/ffp-webui/releases/download/v1.10.0/package.txz',
            'asset_name': 'package.txz',
            'sha256': hashlib.sha256(content).hexdigest(),
            'size': len(content),
        }
        with tempfile.TemporaryDirectory() as root:
            destination = os.path.join(root, 'packages', 'package.txz')
            response = FakeResponse(data=content, headers={'Content-Length': str(len(content))})
            with mock.patch.object(UPDATES, '_open_response', return_value=(FakeConnection(), response)):
                result = UPDATES._download_verified(record, destination, 1024)
            self.assertEqual(result, destination)
            with open(destination, 'rb') as handle:
                self.assertEqual(handle.read(), content)
            self.assertEqual(stat.S_IMODE(os.stat(destination).st_mode), 0o600)

    def test_rejects_bad_digest_and_forbidden_redirect_without_leaving_partial_files(self):
        record = {
            'asset_url': 'https://github.com/PhateValleyman/ffp-webui/releases/download/v1.10.0/package.txz',
            'asset_name': 'package.txz',
            'sha256': hashlib.sha256(b'expected').hexdigest(),
            'size': len(b'wrong'),
        }
        with tempfile.TemporaryDirectory() as root:
            destination = os.path.join(root, 'packages', 'package.txz')
            response = FakeResponse(data=b'wrong', headers={'Content-Length': '5'})
            with mock.patch.object(UPDATES, '_open_response', return_value=(FakeConnection(), response)):
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    UPDATES._download_verified(record, destination, 1024)
            self.assertFalse(os.path.exists(destination))
            self.assertEqual(os.listdir(os.path.dirname(destination)), [])

            redirect = FakeResponse(status=302, headers={'Location': 'https://example.org/evil.txz'})
            with mock.patch.object(UPDATES, '_open_response', return_value=(FakeConnection(), redirect)):
                with self.assertRaisesRegex(ValueError, 'allowed HTTPS hosts'):
                    UPDATES._download_verified(record, destination, 1024)
            self.assertFalse(os.path.exists(destination))
            self.assertEqual(os.listdir(os.path.dirname(destination)), [])

    def test_verified_install_target_rechecks_exact_staged_file_and_digest(self):
        asset_name = 'ffp-webui-1.10.0-python3.13-static-UNVERIFIED.txz'
        content = b'verified package'
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as root:
            packages = os.path.join(root, 'packages')
            os.makedirs(packages)
            path = os.path.join(packages, asset_name)
            with open(path, 'wb') as handle:
                handle.write(content)
            updater = UPDATES.GitHubSelfUpdater('1.9.9', root)
            updater._state.update({'state': 'available', 'asset_name': asset_name,
                                   'staged_path': path, 'sha256': digest})
            self.assertEqual(updater.verified_install_target(), {
                'asset_name': asset_name, 'path': path, 'sha256': digest})
            with open(path, 'wb') as handle:
                handle.write(b'changed package')
            with self.assertRaisesRegex(ValueError, 'digest changed'):
                updater.verified_install_target()

    def test_startup_removes_only_generated_partial_download_files(self):
        with tempfile.TemporaryDirectory() as root:
            packages = os.path.join(root, 'packages')
            os.makedirs(packages)
            generated = os.path.join(packages,
                'ffp-webui-1.2.3-python3.13-static-UNVERIFIED.txz.part-' + 'a' * 32)
            unrelated = os.path.join(packages, 'other-package.txz.part-' + 'b' * 32)
            for path in (generated, unrelated):
                with open(path, 'wb') as handle:
                    handle.write(b'temporary')
            UPDATES.GitHubSelfUpdater('1.2.3', root)
            self.assertFalse(os.path.exists(generated))
            self.assertTrue(os.path.exists(unrelated))

    def test_updater_is_explicitly_download_only_and_does_not_invoke_funpkg(self):
        with open(MODULE_PATH, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('never install', source)
        self.assertNotIn('import subprocess', source)
        self.assertNotIn('os.system(', source)
        self.assertNotIn('execv(', source)


if __name__ == '__main__':
    unittest.main()
