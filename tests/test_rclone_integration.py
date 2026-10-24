import importlib.machinery
import importlib.util
import os
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
BRIDGE_PATH = os.path.join(ROOT, 'ffp', 'ffp', 'bin', 'ffp_webui_rclone.py')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_rclone_test_module', BRIDGE_PATH)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
RCLONE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(RCLONE)


class RclonePathTests(unittest.TestCase):
    def test_remote_paths_normalize_only_safe_components(self):
        self.assertEqual(RCLONE.normalize_remote_path('/folder/sub/file.jpg/'), 'folder/sub/file.jpg')
        for path in ('../secret', 'folder/../secret', 'folder//file', r'folder\\file', 'a\x00b'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    RCLONE.normalize_remote_path(path)

    def test_preview_rejects_large_listed_file_before_starting_process(self):
        bridge = RCLONE.RcloneBridge(None, lambda _: None, lambda: {}, lambda: [])
        bridge.remote_names = lambda: ['drive']
        bridge.files = lambda name, parent: {'entries': [{'name': 'large.mp4', 'directory': False, 'size': 9}]}
        bridge._ensure_server = lambda: self.fail('must reject before starting or contacting rclone')
        with self.assertRaisesRegex(ValueError, '32 MiB'):
            bridge.preview_bytes('drive', 'large.mp4', limit=8)

    def test_preview_reads_bounded_bytes_from_argv_only_child(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = os.path.join(directory, 'fake-rclone')
            with open(executable, 'w', encoding='utf-8') as handle:
                handle.write('#!/bin/sh\nprintf abcde\n')
            os.chmod(executable, 0o700)
            bridge = RCLONE.RcloneBridge(None, lambda _: executable, lambda: os.environ.copy(), lambda: [])
            bridge.remote_names = lambda: ['drive']
            bridge.files = lambda name, parent: {'entries': [{'name': 'cover.png', 'directory': False, 'size': 5}]}
            bridge._ensure_server = lambda: setattr(bridge, 'binary', executable)
            self.assertEqual(bridge.preview_bytes('drive', '/cover.png', limit=8), b'abcde')

    def test_preview_kills_child_when_actual_bytes_exceed_the_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = os.path.join(directory, 'fake-rclone')
            with open(executable, 'w', encoding='utf-8') as handle:
                handle.write('#!/bin/sh\nprintf abcdefghij\n')
            os.chmod(executable, 0o700)
            bridge = RCLONE.RcloneBridge(None, lambda _: executable, lambda: os.environ.copy(), lambda: [])
            bridge.remote_names = lambda: ['drive']
            bridge.files = lambda name, parent: {'entries': [{'name': 'cover.png', 'directory': False, 'size': 4}]}
            bridge._ensure_server = lambda: setattr(bridge, 'binary', executable)
            with self.assertRaisesRegex(RuntimeError, '32 MiB'):
                bridge.preview_bytes('drive', 'cover.png', limit=4)


if __name__ == '__main__':
    unittest.main()
