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


if __name__ == '__main__':
    unittest.main()
