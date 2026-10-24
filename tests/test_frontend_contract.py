import os
import re
import unittest
from collections import Counter


ROOT = os.path.dirname(os.path.dirname(__file__))
HTML_PATH = os.path.join(ROOT, 'internal', 'webui', 'assets', 'index.html')
JS_PATH = os.path.join(ROOT, 'internal', 'webui', 'assets', 'app.js')


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(HTML_PATH, encoding='utf-8') as handle:
            cls.html = handle.read()
        with open(JS_PATH, encoding='utf-8') as handle:
            cls.js = handle.read()

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


if __name__ == '__main__':
    unittest.main()
