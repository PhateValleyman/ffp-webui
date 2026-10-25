import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_package_management_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)


class PackageManagementTests(unittest.TestCase):
    def test_package_detail_reads_only_selected_regular_package_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, 'alpha-1'), 'w', encoding='utf-8') as handle:
                handle.write('./ffp/bin/alpha\n./ffp/etc/alpha.conf\n')
            handler = object.__new__(FFP.Handler)
            handler.path = '/api/packages/detail?name=alpha-1'
            handler.server = SimpleNamespace(app=SimpleNamespace(demo=False))
            with mock.patch.object(handler, 'package_inventory_names', return_value=('/ffp/bin/funpkg', ['alpha-1'])), \
                 mock.patch.object(FFP, 'PACKAGE_DB_DIR', directory), \
                 mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
                status, body = handler.package_detail()
            self.assertEqual(status, 200)
            self.assertTrue(body['available'])
            self.assertEqual(body['file_count'], 2)
            self.assertEqual(body['files'], ['./ffp/bin/alpha', './ffp/etc/alpha.conf'])

    def test_uninstall_verifies_inventory_and_calls_funpkg_remove_by_name(self):
        req = {'name': 'alpha-1', 'confirm': 'REMOVE alpha-1'}
        start_job = mock.Mock(return_value={'id': 'job1'})
        audit = mock.Mock()
        handler = object.__new__(FFP.Handler)
        handler.server = SimpleNamespace(app=SimpleNamespace(
            read_json=lambda _handler, _limit: req,
            cfg={'operation_timeout_seconds': 30},
            start_job=start_job,
            audit=audit,
        ))
        with mock.patch.object(handler, 'package_inventory_names', return_value=('/ffp/bin/funpkg', ['alpha-1'])), \
             mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)), \
             mock.patch.object(FFP, 'run_fixed', return_value='removed') as run:
            status, body = handler.package_uninstall()
            kind, operation = start_job.call_args.args
            result = operation()
        self.assertEqual(status, 202)
        self.assertEqual(body['id'], 'job1')
        self.assertEqual(kind, 'funpkg -r alpha-1')
        run.assert_called_once_with(['/ffp/bin/funpkg', '-r', 'alpha-1'], 30)
        self.assertEqual(result, 'removed')
        self.assertEqual(req, {})
        audit.assert_called_once()

    def test_uninstall_rejects_package_not_in_current_funpkg_inventory(self):
        req = {'name': 'alpha-1', 'confirm': 'REMOVE alpha-1'}
        handler = object.__new__(FFP.Handler)
        handler.server = SimpleNamespace(app=SimpleNamespace(read_json=lambda _handler, _limit: req))
        handler._error = mock.Mock(return_value='rejected')
        with mock.patch.object(handler, 'package_inventory_names', return_value=('/ffp/bin/funpkg', ['beta-2'])):
            result = handler.package_uninstall()
        self.assertEqual(result, 'rejected')
        handler._error.assert_called_once_with(404, 'Package is not in the current funpkg -q . inventory')

    def test_self_update_install_uses_only_verified_staged_path_and_digest(self):
        asset_name = 'ffp-webui-1.10.0-python3.13-static-UNVERIFIED.txz'
        staged_path = '/ffp/var/ffp-webui/packages/' + asset_name
        digest = 'a' * 64
        req = {'confirm': 'UPGRADE ' + asset_name}
        start_job = mock.Mock(return_value={'id': 'job2'})
        audit = mock.Mock()
        target = {'asset_name': asset_name, 'path': staged_path, 'sha256': digest}
        app = SimpleNamespace(
            require_live=lambda _handler: True,
            read_json=lambda _handler, _limit: req,
            self_updater=SimpleNamespace(verified_install_target=mock.Mock(return_value=target)),
            package_path=mock.Mock(side_effect=lambda path: path),
            cfg={'operation_timeout_seconds': 30},
            start_job=start_job,
            audit=audit,
        )
        handler = object.__new__(FFP.Handler)
        handler.server = SimpleNamespace(app=app)
        with mock.patch.object(FFP, 'command_path', return_value='/ffp/bin/funpkg'), \
             mock.patch.object(FFP, 'sha256_file', return_value=digest), \
             mock.patch.object(FFP, 'run_fixed', side_effect=['installed', asset_name[:-4]]) as run, \
             mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
            status, body = handler.self_update_install()
            kind, operation = start_job.call_args.args
            result = operation()
        self.assertEqual((status, body), (202, {'id': 'job2'}))
        self.assertEqual(kind, 'funpkg -i verified ' + asset_name)
        app.self_updater.verified_install_target.assert_called_once_with()
        app.package_path.assert_called_once_with(staged_path)
        run.assert_has_calls([
            mock.call(['/ffp/bin/funpkg', '-i', staged_path], 30),
            mock.call(['/ffp/bin/funpkg', '-q', '.'], 20),
        ])
        self.assertEqual(result, 'installed')
        audit.assert_called_once_with(handler, 'package_self_update', asset_name, 'started')
        self.assertEqual(req, {})

    def test_self_update_install_fails_if_funpkg_inventory_lacks_release(self):
        asset_name = 'ffp-webui-1.10.0-python3.13-static-UNVERIFIED.txz'
        staged_path = '/ffp/var/ffp-webui/packages/' + asset_name
        digest = 'a' * 64
        req = {'confirm': 'UPGRADE ' + asset_name}
        start_job = mock.Mock(return_value={'id': 'job3'})
        app = SimpleNamespace(
            require_live=lambda _handler: True,
            read_json=lambda _handler, _limit: req,
            self_updater=SimpleNamespace(verified_install_target=mock.Mock(return_value={
                'asset_name': asset_name, 'path': staged_path, 'sha256': digest})),
            package_path=lambda path: path,
            cfg={'operation_timeout_seconds': 30},
            start_job=start_job,
            audit=mock.Mock(),
        )
        handler = object.__new__(FFP.Handler)
        handler.server = SimpleNamespace(app=app)
        with mock.patch.object(FFP, 'command_path', return_value='/ffp/bin/funpkg'), \
             mock.patch.object(FFP, 'sha256_file', return_value=digest), \
             mock.patch.object(FFP, 'run_fixed', side_effect=[
                 'Not installed', 'ffp-webui-0.9.4-python3.13-static-UNVERIFIED']), \
             mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)):
            status, body = handler.self_update_install()
            _kind, operation = start_job.call_args.args
            self.assertEqual((status, body), (202, {'id': 'job3'}))
            with self.assertRaisesRegex(RuntimeError, 'did not report the FFP-WebUI update as installed'):
                operation()

    def test_self_update_install_rejects_client_path_override(self):
        req = {'confirm': 'UPGRADE archive.txz', 'path': '/ffp/pkg/archive.txz', 'sha256': 'b' * 64}
        start_job = mock.Mock()
        updater = SimpleNamespace(verified_install_target=mock.Mock())
        app = SimpleNamespace(
            require_live=lambda _handler: True,
            read_json=lambda _handler, _limit: req,
            self_updater=updater,
            start_job=start_job,
        )
        handler = object.__new__(FFP.Handler)
        handler.server = SimpleNamespace(app=app)
        handler._error = mock.Mock(return_value='rejected')
        result = handler.self_update_install()
        self.assertEqual(result, 'rejected')
        handler._error.assert_called_once_with(400, 'Only an exact update confirmation is accepted')
        updater.verified_install_target.assert_not_called()
        start_job.assert_not_called()

    def test_self_update_install_refuses_changed_staged_digest(self):
        asset_name = 'ffp-webui-1.10.0-python3.13-static-UNVERIFIED.txz'
        staged_path = '/ffp/var/ffp-webui/packages/' + asset_name
        req = {'confirm': 'UPGRADE ' + asset_name}
        app = SimpleNamespace(
            require_live=lambda _handler: True,
            read_json=lambda _handler, _limit: req,
            self_updater=SimpleNamespace(verified_install_target=mock.Mock(return_value={
                'asset_name': asset_name, 'path': staged_path, 'sha256': 'a' * 64})),
            package_path=lambda path: path,
            start_job=mock.Mock(),
        )
        handler = object.__new__(FFP.Handler)
        handler.server = SimpleNamespace(app=app)
        handler._error = mock.Mock(return_value='rejected')
        with mock.patch.object(FFP, 'sha256_file', return_value='b' * 64):
            result = handler.self_update_install()
        self.assertEqual(result, 'rejected')
        handler._error.assert_called_once_with(422, 'Verified installer SHA-256 changed; funpkg was not run')
        app.start_job.assert_not_called()


if __name__ == '__main__':
    unittest.main()
