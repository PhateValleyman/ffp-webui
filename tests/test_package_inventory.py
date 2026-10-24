import importlib.machinery
import importlib.util
import os
import unittest
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_package_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)


class PackageInventoryTests(unittest.TestCase):
    def test_inventory_uses_funpkg_quiet_current_directory(self):
        backend = object.__new__(FFP.Backend)
        backend.cfg = {'package_roots': ['/path/that/does/not/exist'], 'max_package_bytes': 1024}
        with mock.patch.object(FFP, 'command_path', return_value='/ffp/bin/funpkg'), \
             mock.patch.object(FFP, 'run_fixed', return_value='alpha-1\n\nbeta-2\n') as run:
            result = backend.packages()
        run.assert_called_once_with(['/ffp/bin/funpkg', '-q', '.'], 20)
        self.assertEqual(result['inventory_source'], 'funpkg -q .')
        self.assertEqual(result['installed'], ['alpha-1', 'beta-2'])
        self.assertEqual(result['inventory_status'], 'ok')

    def test_unavailable_funpkg_is_not_reported_as_empty_success(self):
        backend = object.__new__(FFP.Backend)
        backend.cfg = {'package_roots': ['/path/that/does/not/exist'], 'max_package_bytes': 1024}
        with mock.patch.object(FFP, 'command_path', return_value=None):
            result = backend.packages()
        self.assertEqual(result['inventory_status'], 'error')
        self.assertIn('unavailable', result['inventory_error'])
        self.assertEqual(result['installed'], [])


if __name__ == '__main__':
    unittest.main()
