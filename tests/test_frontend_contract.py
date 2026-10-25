import os
import re
import unittest
from collections import Counter


ROOT = os.path.dirname(os.path.dirname(__file__))
HTML_PATH = os.path.join(ROOT, 'internal', 'webui', 'assets', 'index.html')
JS_PATH = os.path.join(ROOT, 'internal', 'webui', 'assets', 'app.js')
BACKEND_PATH = os.path.join(ROOT, 'ffp', 'ffp', 'bin', 'ffp-webui')
RCLONE_PATH = os.path.join(ROOT, 'ffp', 'ffp', 'bin', 'ffp_webui_rclone.py')


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(HTML_PATH, encoding='utf-8') as handle:
            cls.html = handle.read()
        with open(JS_PATH, encoding='utf-8') as handle:
            cls.js = handle.read()
        with open(BACKEND_PATH, encoding='utf-8') as handle:
            cls.backend = handle.read()
        with open(RCLONE_PATH, encoding='utf-8') as handle:
            cls.rclone = handle.read()

    def test_new_fixed_controls_exist_and_ids_are_unique(self):
        ids = re.findall(r'\bid="([^"]+)"', self.html)
        duplicates = [name for name, count in Counter(ids).items() if count > 1]
        self.assertEqual(duplicates, [])
        for element_id in ('file-bookmark-save-left', 'file-bookmark-save-right',
                           'file-bookmarks-list', 'terminal-open-files', 'terminal-save-bookmark', 'terminal-input'):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)
                self.assertIn(f"$('#{element_id}')", self.js)

    def test_touch_terminal_key_pad_contains_expected_function_keys_and_modifiers(self):
        for key in ('f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10',
                    'up', 'down', 'left', 'right', 'home', 'end', 'enter', 'tab', 'esc'):
            with self.subTest(key=key):
                self.assertIn(f'data-terminal-key="{key}"', self.html)
        self.assertIn('data-terminal-modifier="ctrl"', self.html)
        self.assertIn('data-terminal-modifier="shift"', self.html)
        self.assertIn('terminalModifiers.ctrl', self.js)
        self.assertIn('terminalModifiers.shift', self.js)

    def test_cross_backend_preview_and_script_routes_are_wired(self):
        self.assertIn('/api/adb/preview?', self.js)
        self.assertIn('/api/rclone/preview?', self.js)
        self.assertIn('/api/adb/run-script', self.js)
        self.assertIn("function openFilesFromTerminal()", self.js)
        self.assertIn('function saveTerminalBookmark()', self.js)

    def test_rclone_remote_management_and_oauth_contracts_exist(self):
        for endpoint in ('/api/rclone/remote', '/api/rclone/config/update',
                         '/api/rclone/config/delete', '/api/rclone/oauth',
                         '/api/rclone/oauth/stop'):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, self.js)
                self.assertIn(endpoint, self.backend)
        self.assertIn('secret_fields', self.rclone)
        self.assertIn('rcloneEditProfile', self.js)
        self.assertIn('rclone authorize', self.js)
        self.assertIn("if (clear) parameters[key] = '';", self.js)
        self.assertIn("else if (field.value !== '') parameters[key] = field.value;", self.js)
        self.assertIn('setInterval(refreshRcloneOAuthStatus, 5000)', self.js)

    def test_panel_method_routes_and_release_mismatch_diagnostics_exist(self):
        self.assertIn("api(`/api/adb/files?", self.js)
        self.assertIn("api(`/api/rclone/files?", self.js)
        self.assertIn("path == '/api/adb/files' and self.command == 'GET'", self.backend)
        self.assertIn("path == '/api/rclone/files' and self.command == 'GET'", self.backend)
        self.assertIn("'server_version': WEBUI_VERSION", self.backend)
        self.assertIn('backend-version-warning', self.html)
        self.assertIn('Cache-Control', self.backend)


if __name__ == '__main__':
    unittest.main()
