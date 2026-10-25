import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from unittest.mock import Mock


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


class RcloneConfigTests(unittest.TestCase):
    def make_bridge(self, config=None):
        bridge = RCLONE.RcloneBridge(None, lambda _: None, lambda: {}, lambda: [])
        provider = {'name': 's3', 'description': '', 'options': [
            {'name': 'region', 'type': 'string', 'default': 'us-east-1', 'required': False,
             'password': False, 'sensitive': False, 'exclusive': False, 'advanced': False, 'examples': []},
            {'name': 'secret_access_key', 'type': 'string', 'default': '', 'required': False,
             'password': True, 'sensitive': False, 'exclusive': False, 'advanced': False, 'examples': []},
            {'name': 'token', 'type': 'string', 'default': '', 'required': False,
             'password': False, 'sensitive': True, 'exclusive': False, 'advanced': False, 'examples': []}]}
        bridge.providers = lambda force=False: [provider]
        bridge.remote_names = lambda: ['drive'] if config is not None else []
        bridge.remote_config = lambda name: dict(config or {})
        return bridge

    def test_edit_profile_never_returns_secret_values(self):
        bridge = self.make_bridge({'type': 's3', 'region': 'eu-west-2',
                                   'secret_access_key': 'secret-value', 'token': '{"access":"private"}'})
        profile = bridge.remote_edit_profile('drive')
        self.assertEqual(profile['values'], {'region': 'eu-west-2'})
        self.assertEqual(set(profile['secret_fields']), {'secret_access_key', 'token'})
        self.assertNotIn('secret-value', repr(profile))
        self.assertNotIn('private', repr(profile))

    def test_update_and_followup_use_config_update_and_return_action(self):
        bridge = self.make_bridge({'type': 's3', 'region': 'us-east-1'})
        bridge.rc_call = Mock(side_effect=[
            {'State': 'opaque-state', 'Option': {'Name': 'confirm', 'Type': 'bool'}},
            {}
        ])
        pending = bridge.update_remote({'name': 'drive', 'type': 's3', 'parameters': {'region': 'eu-west-2'}})
        self.assertFalse(pending['complete'])
        self.assertEqual(bridge.config_sessions[pending['session_id']]['operation'], 'update')
        self.assertEqual(bridge.rc_call.call_args_list[0].args[0], 'config/update')
        self.assertNotIn('type', bridge.rc_call.call_args_list[0].args[1])
        result = bridge.continue_remote({'session_id': pending['session_id'], 'result': 'true'})
        self.assertTrue(result['complete'])
        self.assertEqual(result['action'], 'update')
        self.assertEqual(bridge.rc_call.call_args_list[1].args[0], 'config/update')

    def test_delete_requires_exact_remote_confirmation_and_only_deletes_config(self):
        bridge = self.make_bridge({'type': 's3'})
        bridge.rc_call = Mock(return_value={})
        with self.assertRaisesRegex(ValueError, 'Exact remote deletion confirmation'):
            bridge.delete_remote({'name': 'drive', 'confirm': 'delete drive'})
        result = bridge.delete_remote({'name': 'drive', 'confirm': 'DELETE RCLONE REMOTE drive'})
        self.assertEqual(result, {'ok': True, 'remote': 'drive'})
        self.assertEqual(bridge.rc_call.call_args.args[0], 'config/delete')
        self.assertEqual(bridge.rc_call.call_args.args[1], {'name': 'drive'})

    def test_oauth_status_falls_back_when_target_rclone_lacks_new_api(self):
        bridge = self.make_bridge()
        bridge.rc_call = Mock(side_effect=RuntimeError('rclone config/oauthstatus: method not found'))
        status = bridge.oauth_status()
        self.assertFalse(status['supported'])
        self.assertEqual(status['status'], 'unsupported')

    def test_oauth_status_accepts_only_loopback_callback_url(self):
        bridge = self.make_bridge()
        bridge.rc_call = Mock(return_value={'status': 'running', 'authUrl': 'http://127.0.0.1:53682/auth?state=abc'})
        status = bridge.oauth_status()
        self.assertTrue(status['supported'])
        self.assertTrue(status['requires_loopback'])
        bridge.rc_call = Mock(return_value={'status': 'running', 'authUrl': 'https://attacker.example/auth'})
        with self.assertRaisesRegex(RuntimeError, 'unexpected OAuth callback URL'):
            bridge.oauth_status()

    def test_oauth_stop_calls_rc_only_for_running_flow(self):
        bridge = self.make_bridge()
        bridge.oauth_status = Mock(return_value={'supported': True, 'status': 'running'})
        bridge.rc_call = Mock(return_value={})
        self.assertEqual(bridge.oauth_stop(), {'stopped': True, 'supported': True})
        bridge.rc_call.assert_called_once_with('config/oauthstop', {})
        bridge.oauth_status.return_value = {'supported': True, 'status': 'stopped'}
        bridge.rc_call.reset_mock()
        self.assertEqual(bridge.oauth_stop(), {'stopped': False, 'supported': True})
        bridge.rc_call.assert_not_called()

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
