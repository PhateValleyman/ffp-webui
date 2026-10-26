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

    def test_luanti_paths_can_be_saved_before_world_or_account_selection(self):
        self.assertIn('id="luanti-paths-save"', self.html)
        self.assertIn("path == '/api/luanti/paths' and self.command == 'POST'", self.backend)
        self.assertIn('def luanti_paths_save(self):', self.backend)
        start = self.backend.index('def luanti_paths_save(self):')
        end = self.backend.index('def luanti_config_save(self):', start)
        paths_handler = self.backend[start:end]
        self.assertIn('update_paths_only(paths)', paths_handler)
        self.assertIn('if not isinstance(data, dict)', paths_handler)
        self.assertIn('isinstance(exc, OSError)', self.backend)
        start = self.js.index('async function saveLuantiPaths()')
        end = self.js.index("$('#luanti-paths-save').addEventListener", start)
        path_save = self.js[start:end]
        self.assertIn("post('/api/luanti/paths', { paths })", path_save)
        self.assertNotIn('run_as_user', path_save)
        self.assertNotIn('selected_world', path_save)

    def test_zypkg_firmware_shortcuts_are_separate_from_funpkg_management(self):
        self.assertIn('id="zypkg-manager"', self.html)
        self.assertIn('Správa Zypkg balíčků', self.html)
        self.assertIn('/r49435,/adv,/admin/firmware_package.html', self.html)
        self.assertIn('/r49435,/adv,/admin/apps_package_mgmt_install.html', self.html)
        self.assertIn('Samostatný správce firmwaru; není součástí FFP/funpkg.', self.html)
        self.assertIn('Automatická aktualizace FFP-WebUI je oddělená', self.html)
        self.assertIn("'/api/packages/catalog'", self.backend)
        self.assertIn("path == '/api/packages/catalog/action' and self.command == 'POST'", self.backend)
        self.assertIn("path == '/api/zypkg' and self.command == 'GET'", self.backend)
        self.assertIn("`/api/zypkg?${params.toString()}`", self.js)
        self.assertIn("'/api/zypkg/update-list'", self.backend)
        for query in ('zy-pkgs query all', 'zy-pkgs query newver', 'zy-pkgs query status', 'zy-pkgs update-list showProgress'):
            with self.subTest(query=query):
                self.assertIn(query, self.backend)
        self.assertIn("'/api/zypkg/action'", self.js)
        self.assertIn("'/api/zypkg/update-list'", self.js)
        self.assertIn('Exact Zypkg action confirmation required', self.backend)
        self.assertIn("if (!needsVersion) $('#zypkg-action-version').value = ''", self.js)
        self.assertIn("const version = ['install', 'uninstall'].includes(action)", self.js)

    def test_button_confirmation_dialog_replaces_all_typed_action_gates(self):
        self.assertEqual(len(re.findall(r"\bconfirmGuardedAction\(", self.js)) - 1, 42)
        self.assertNotRegex(self.js, r"\b(?:window\.)?confirm\s*\(")
        self.assertNotRegex(self.js, r"if\s*\(\s*prompt\s*\(")
        self.assertIn("actionConfirmDialog.showModal()", self.js)
        self.assertIn("actionConfirmDialog.close('confirm')", self.js)
        self.assertIn("actionConfirmDialog.close('cancel')", self.js)
        self.assertIn("actionConfirmCancel.focus()", self.js)
        self.assertIn("event.key === 'Enter' && event.target === actionConfirmDialog", self.js)
        self.assertIn("actionConfirmDialog.returnValue === 'confirm'", self.js)
        self.assertIn("confirm: confirmText", self.js)
        dialog_start = self.html.index('<dialog id="action-confirm-dialog"')
        dialog_end = self.html.index('</dialog>', dialog_start)
        dialog = self.html[dialog_start:dialog_end]
        self.assertIn('aria-labelledby="action-confirm-title"', dialog)
        self.assertIn('aria-describedby="action-confirm-message"', dialog)
        self.assertNotIn('<form', dialog)
        self.assertEqual(dialog.count('type="button"'), 2)
        self.assertIn('id="action-confirm-cancel"', dialog)
        self.assertIn('id="action-confirm-accept"', dialog)

    def test_release_version_is_consistent_across_backend_frontend_and_build(self):
        self.assertIn("WEBUI_VERSION = '0.12.3'", self.backend)
        self.assertIn("FRONTEND_VERSION = '0.12.3'", self.js)
        self.assertIn('WebUI 0.12.3 · Python', self.html)
        with open(os.path.join(ROOT, 'build.sh'), encoding='utf-8') as handle:
            self.assertIn('VERSION=${VERSION:-0.12.3}', handle.read())

    def test_github_update_stages_only_ffp_webui_and_manual_install_is_in_browser(self):
        for endpoint in ('/api/self-update', '/api/self-update/check', '/api/self-update/install'):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, self.js)
                self.assertIn(endpoint, self.backend)
        for element_id in ('self-update-status', 'self-update-check', 'self-update-install', 'self-update-release'):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('POUZE FFP-WEBUI', self.html)
        self.assertIn('SHA-256', self.backend)
        self.assertIn('item.path === data.staged_path && item.sha256 === data.sha256', self.js)
        self.assertIn("post('/api/self-update/install', { confirm: confirmText })", self.js)
        self.assertNotIn("packageAction(archive, 'upgrade')", self.js)
        self.assertIn('def self_update_install(self):', self.backend)
        self.assertIn('verified_install_target()', self.backend)
        self.assertIn('GitHubSelfUpdater', self.backend)
        self.assertIn("run_fixed([funpkg, '-i', package]", self.backend)
        self.assertIn("run_fixed([funpkg, '-q', '.']", self.backend)
        self.assertIn('WebUI samo nevytváří zálohu ani rollback', self.js)
        self.assertIn('/ffp/funpkg/installed/ffp-webui-*', self.js)
        updater_path = os.path.join(ROOT, 'ffp', 'ffp', 'bin', 'ffp_webui_update.py')
        with open(updater_path, encoding='utf-8') as handle:
            updater = handle.read()
        self.assertIn('release-assets.githubusercontent.com', updater)
        self.assertIn('def verified_install_target(self):', updater)
        self.assertIn('digest changed after staging', updater)
        self.assertNotIn('subprocess', updater)
        self.assertNotIn('os.system(', updater)


if __name__ == '__main__':
    unittest.main()
