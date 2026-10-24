import importlib.machinery
import importlib.util
import os
import unittest
from types import SimpleNamespace
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_tweaks_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)


class TweaksMonitorTests(unittest.TestCase):
    def make_handler(self, demo):
        handler = object.__new__(FFP.Handler)
        handler.server = SimpleNamespace(app=SimpleNamespace(demo=demo))
        return handler

    def test_demo_does_not_inspect_host_processes_or_sockets(self):
        handler = self.make_handler(True)
        with mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
            status, body = handler.tweaks_get()
        self.assertEqual(status, 200)
        self.assertFalse(body['available'])
        self.assertEqual(body['processes'], [])
        self.assertEqual(body['sockets'], [])

    def test_live_snapshot_is_read_only_and_omits_command_lines(self):
        handler = self.make_handler(False)
        with mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
            status, body = handler.tweaks_get()
        self.assertEqual(status, 200)
        self.assertTrue(body['available'])
        self.assertIsInstance(body['ips'], list)
        self.assertIsInstance(body['sockets'], list)
        self.assertIsInstance(body['processes'], list)
        self.assertGreaterEqual(body['process_count'], 1)
        self.assertLessEqual(len(body['processes']), 100)
        self.assertLessEqual(len(body['sockets']), 200)
        for process in body['processes']:
            self.assertNotIn('cmdline', process)
            self.assertIn('pid', process)
            self.assertIn('rss_kb', process)
        for socket in body['sockets']:
            self.assertIn(socket['protocol'], ('TCP', 'TCP6', 'UDP', 'UDP6'))
            self.assertIn('local', socket)
            self.assertIn('state', socket)


if __name__ == '__main__':
    unittest.main()
