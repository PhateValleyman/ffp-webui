import importlib.machinery
import importlib.util
import os
import unittest
from types import SimpleNamespace
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_zypkg_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)


class ZypkgTests(unittest.TestCase):
    def make_handler(self, path, app=None):
        handler = object.__new__(FFP.Handler)
        handler.path = path
        handler.server = SimpleNamespace(app=app or SimpleNamespace(demo=False))
        return handler

    def test_read_only_query_uses_fixed_zysh_command(self):
        handler = self.make_handler('/api/zypkg?view=all')
        with mock.patch.object(FFP, 'command_path', return_value='/bin/zysh'), \
             mock.patch.object(FFP, 'run_fixed', return_value='package list') as run, \
             mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
            status, body = handler.zypkg_query()
        self.assertEqual(status, 200)
        self.assertTrue(body['available'])
        self.assertEqual(body['output'], 'package list')
        run.assert_called_once_with(['/bin/zysh', '-e', 'zy-pkgs query all'], 45)

    def test_read_only_package_query_validates_name_before_interpolating(self):
        handler = self.make_handler('/api/zypkg?view=package&name=meta-repo')
        with mock.patch.object(FFP, 'command_path', return_value='/bin/zysh'), \
             mock.patch.object(FFP, 'run_fixed', return_value='package details') as run, \
             mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
            status, body = handler.zypkg_query()
        self.assertEqual(status, 200)
        self.assertEqual(body['command'], 'zy-pkgs query "meta-repo"')
        run.assert_called_once_with(['/bin/zysh', '-e', 'zy-pkgs query "meta-repo"'], 45)

    def test_query_rejects_command_injection_and_unknown_views(self):
        for path in ('/api/zypkg?view=package&name=x%22%3Breboot',
                     '/api/zypkg?view=arbitrary'):
            with self.subTest(path=path):
                handler = self.make_handler(path)
                handler._error = mock.Mock(return_value='rejected')
                with mock.patch.object(FFP, 'run_fixed') as run:
                    self.assertEqual(handler.zypkg_query(), 'rejected')
                handler._error.assert_called_once_with(400, mock.ANY)
                run.assert_not_called()

    def test_demo_query_does_not_run_zysh(self):
        handler = self.make_handler('/api/zypkg?view=status', SimpleNamespace(demo=True))
        with mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)), \
             mock.patch.object(FFP, 'run_fixed') as run:
            status, body = handler.zypkg_query()
        self.assertEqual(status, 200)
        self.assertTrue(body['demo'])
        self.assertFalse(body['available'])
        run.assert_not_called()

    def test_install_uses_confirmed_name_and_version_without_shell(self):
        request = {'action': 'install', 'name': 'transmission', 'version': '2.77_arm_001',
                   'confirm': 'INSTALL transmission 2.77_arm_001'}
        start_job = mock.Mock(return_value={'id': 'zy1'})
        audit = mock.Mock()
        app = SimpleNamespace(
            read_json=lambda _handler, _limit: request,
            cfg={'operation_timeout_seconds': 300},
            start_job=start_job,
            audit=audit,
        )
        handler = self.make_handler('/api/zypkg/action', app)
        with mock.patch.object(FFP, 'command_path', return_value='/bin/zysh'), \
             mock.patch.object(FFP, 'run_fixed', return_value='installed') as run, \
             mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
            status, body = handler.zypkg_action()
            kind, operation = start_job.call_args.args
            output = operation()
        self.assertEqual((status, body), (202, {'id': 'zy1'}))
        self.assertEqual(kind, 'zy-pkgs install transmission')
        run.assert_called_once_with(['/bin/zysh', '-e', 'zy-pkgs install "transmission" 2.77_arm_001'], 300)
        self.assertEqual(output, 'installed')
        self.assertEqual(request, {})
        audit.assert_called_once_with(handler, 'zypkg_install', 'transmission', 'started')

    def test_uninstall_uses_the_firmware_command_argument_shape(self):
        request = {'action': 'uninstall', 'name': 'transmission', 'version': '2.77_arm_001',
                   'confirm': 'UNINSTALL transmission 2.77_arm_001'}
        app = SimpleNamespace(
            read_json=lambda _handler, _limit: request,
            cfg={'operation_timeout_seconds': 300},
            start_job=mock.Mock(return_value={'id': 'zy2'}),
            audit=mock.Mock(),
        )
        handler = self.make_handler('/api/zypkg/action', app)
        with mock.patch.object(FFP, 'command_path', return_value='/bin/zysh'), \
             mock.patch.object(FFP, 'run_fixed', return_value='removed') as run, \
             mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
            status, _body = handler.zypkg_action()
            _kind, operation = app.start_job.call_args.args
            operation()
        self.assertEqual(status, 202)
        run.assert_called_once_with(['/bin/zysh', '-e', 'zy-pkgs uninstall "transmission" "2.77_arm_001"'], 300)

    def test_update_enable_and_disable_use_only_mapped_commands(self):
        expected_commands = {
            'update': 'zy-pkgs update "transmission"',
            'enable': 'zy-pkgs enable "transmission"',
            'disable': 'zy-pkgs disable "transmission"',
        }
        for action, command in expected_commands.items():
            with self.subTest(action=action):
                request = {'action': action, 'name': 'transmission', 'version': '',
                           'confirm': action.upper() + ' transmission'}
                app = SimpleNamespace(
                    read_json=lambda _handler, _limit, req=request: req,
                    cfg={'operation_timeout_seconds': 300},
                    start_job=mock.Mock(return_value={'id': 'zy-action'}),
                    audit=mock.Mock(),
                )
                handler = self.make_handler('/api/zypkg/action', app)
                with mock.patch.object(FFP, 'command_path', return_value='/bin/zysh'), \
                     mock.patch.object(FFP, 'run_fixed', return_value='done') as run, \
                     mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
                    status, _body = handler.zypkg_action()
                    _kind, operation = app.start_job.call_args.args
                    operation()
                self.assertEqual(status, 202)
                run.assert_called_once_with(['/bin/zysh', '-e', command], 300)

    def test_invalid_name_version_or_confirmation_never_starts_job(self):
        cases = [
            {'action': 'install', 'name': 'pkg";reboot', 'version': '1', 'confirm': 'INSTALL pkg 1'},
            {'action': 'install', 'name': 'pkg', 'version': '1;reboot', 'confirm': 'INSTALL pkg 1;reboot'},
            {'action': 'install', 'name': 'pkg', 'version': '1', 'confirm': 'INSTALL pkg wrong'},
        ]
        for request in cases:
            with self.subTest(request=request):
                app = SimpleNamespace(read_json=lambda _handler, _limit, req=request: req,
                                      start_job=mock.Mock(), audit=mock.Mock())
                handler = self.make_handler('/api/zypkg/action', app)
                handler._error = mock.Mock(return_value='rejected')
                self.assertEqual(handler.zypkg_action(), 'rejected')
                app.start_job.assert_not_called()

    def test_update_list_requires_exact_confirmation(self):
        request = {'confirm': 'UPDATE ZYPKG LISTS'}
        app = SimpleNamespace(
            read_json=lambda _handler, _limit: request,
            cfg={'operation_timeout_seconds': 300},
            start_job=mock.Mock(return_value={'id': 'zy3'}),
            audit=mock.Mock(),
        )
        handler = self.make_handler('/api/zypkg/update-list', app)
        with mock.patch.object(FFP, 'command_path', return_value='/bin/zysh'), \
             mock.patch.object(FFP, 'run_fixed', return_value='started') as run, \
             mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
            status, body = handler.zypkg_update_list()
            _kind, operation = app.start_job.call_args.args
            operation()
        self.assertEqual((status, body), (202, {'id': 'zy3'}))
        run.assert_called_once_with(['/bin/zysh', '-e', 'zy-pkgs update-list start'], 300)
        self.assertEqual(request, {})

    def test_update_list_rejects_inexact_confirmation_without_starting_job(self):
        app = SimpleNamespace(read_json=lambda _handler, _limit: {'confirm': 'UPDATE ALL'},
                              start_job=mock.Mock())
        handler = self.make_handler('/api/zypkg/update-list', app)
        handler._error = mock.Mock(return_value='rejected')
        self.assertEqual(handler.zypkg_update_list(), 'rejected')
        handler._error.assert_called_once_with(400, 'Exact Zypkg list-update confirmation required')
        app.start_job.assert_not_called()


if __name__ == '__main__':
    unittest.main()
