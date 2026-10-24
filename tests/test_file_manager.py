import importlib.machinery
import importlib.util
import io
import os
import tempfile
import tarfile
import unittest
import zipfile
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_files_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)


class FileManagerTests(unittest.TestCase):
    def setUp(self):
        self.backend = object.__new__(FFP.Backend)
        self.backend.cfg = {'allowed_roots': ['/']}

    def test_filesystem_root_is_valid_and_other_paths_are_resolved(self):
        self.assertEqual(self.backend.secure_path('/'), '/')
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'file.txt')
            with open(path, 'w') as handle:
                handle.write('hello')
            self.assertEqual(self.backend.secure_path(path), os.path.realpath(path))

    def test_symlink_components_are_rejected_outside_the_managed_ffp_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            real = os.path.join(directory, 'real')
            os.mkdir(real)
            alias = os.path.join(directory, 'alias')
            os.symlink(real, alias)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                self.backend.secure_path(alias)

    def test_profile_allowlist_includes_fixed_files_and_direct_profile_d_scripts_only(self):
        for path in FFP.PROFILE_FIXED_PATHS:
            self.assertTrue(FFP.is_environment_profile_path(path), path)
        self.assertTrue(FFP.is_environment_profile_path('/ffp/etc/profile.d/login.sh'))
        self.assertFalse(FFP.is_environment_profile_path('/ffp/etc/profile.d/sub/login.sh'))
        self.assertFalse(FFP.is_environment_profile_path('/ffp/etc/profile.d/login.conf'))

    def test_missing_profile_is_creatable_only_when_parent_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(FFP.environment_profile_parent_exists(self.backend, os.path.join(directory, '.profile')))
            self.assertFalse(FFP.environment_profile_parent_exists(self.backend, os.path.join(directory, 'missing', '.profile')))

    def test_state_root_and_its_ancestors_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            state = os.path.join(directory, 'var', 'ffp-webui')
            with mock.patch.object(FFP, 'STATE_ROOT', state):
                self.assertTrue(FFP.contains_state_path(os.path.join(directory, 'var')))
                self.assertTrue(FFP.contains_state_path(state))
                self.assertFalse(FFP.contains_state_path(os.path.join(directory, 'etc')))

    def test_funpkg_database_is_protected_from_general_file_manager(self):
        self.assertTrue(FFP.is_sensitive('/ffp/var/packages'))
        self.assertTrue(FFP.is_sensitive('/ffp/var/packages/bash-5.2'))
        self.assertFalse(FFP.is_sensitive('/ffp/pkg/packages/bash-5.2.txz'))

    def test_tar_archive_round_trip_streams_and_skips_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, 'source')
            dest = os.path.join(directory, 'dest')
            os.mkdir(source)
            os.mkdir(dest)
            with open(os.path.join(source, 'hello.txt'), 'wb') as handle:
                handle.write(b'hello archive')
            os.symlink('/etc/passwd', os.path.join(source, 'outside-link'))
            archive = os.path.join(directory, 'source.tar.gz')
            info = FFP.create_tar_gz(source, archive, 'source')
            self.assertEqual(info['bytes'], len(b'hello archive'))
            result = FFP.extract_archive_safe(archive, dest)
            self.assertEqual(result['files'], 1)
            with open(os.path.join(dest, 'source', 'hello.txt'), 'rb') as handle:
                self.assertEqual(handle.read(), b'hello archive')
            self.assertFalse(os.path.lexists(os.path.join(dest, 'source', 'outside-link')))

    def test_tar_path_traversal_is_rejected_without_writing_outside_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = os.path.join(directory, 'bad.tar.gz')
            destination = os.path.join(directory, 'destination')
            os.mkdir(destination)
            with tarfile.open(archive_path, 'w:gz') as archive:
                info = tarfile.TarInfo('../escape.txt')
                data = b'bad'
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            with self.assertRaisesRegex(ValueError, 'traversal'):
                FFP.extract_archive_safe(archive_path, destination)
            self.assertFalse(os.path.exists(os.path.join(directory, 'escape.txt')))
            self.assertEqual(os.listdir(destination), [])

    def test_archive_cannot_write_into_webui_state_through_its_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, 'ffp')
            state = os.path.join(root, 'var', 'ffp-webui')
            os.makedirs(state)
            archive_path = os.path.join(directory, 'state.tar.gz')
            with tarfile.open(archive_path, 'w:gz') as archive:
                info = tarfile.TarInfo('var/ffp-webui/evil.txt')
                data = b'not allowed'
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            with mock.patch.object(FFP, 'STATE_ROOT', state):
                with self.assertRaisesRegex(ValueError, 'WebUI state'):
                    FFP.extract_archive_safe(archive_path, root)
            self.assertFalse(os.path.exists(os.path.join(state, 'evil.txt')))

    def test_tar_root_entries_count_toward_archive_entry_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = os.path.join(directory, 'many-root-entries.tar.gz')
            destination = os.path.join(directory, 'destination')
            os.mkdir(destination)
            with tarfile.open(archive_path, 'w:gz') as archive:
                for _ in range(3):
                    archive.addfile(tarfile.TarInfo('.'))
            with mock.patch.object(FFP, 'MAX_ARCHIVE_FILES', 2):
                with self.assertRaisesRegex(ValueError, 'entry limit'):
                    FFP.extract_archive_safe(archive_path, destination)

    def test_zip_conflicts_do_not_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = os.path.join(directory, 'files.zip')
            destination = os.path.join(directory, 'destination')
            os.mkdir(destination)
            with open(os.path.join(destination, 'existing.txt'), 'wb') as handle:
                handle.write(b'original')
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('existing.txt', 'replacement')
            with self.assertRaises(FileExistsError):
                FFP.extract_archive_safe(archive_path, destination)
            with open(os.path.join(destination, 'existing.txt'), 'rb') as handle:
                self.assertEqual(handle.read(), b'original')

    def test_zip_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = os.path.join(directory, 'bad.zip')
            destination = os.path.join(directory, 'destination')
            os.mkdir(destination)
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('../escape.txt', 'bad')
            with self.assertRaisesRegex(ValueError, 'traversal'):
                FFP.extract_archive_safe(archive_path, destination)
            self.assertFalse(os.path.exists(os.path.join(directory, 'escape.txt')))


if __name__ == '__main__':
    unittest.main()
