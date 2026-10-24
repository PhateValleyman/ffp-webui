import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_ssh_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)


class SSHInputTests(unittest.TestCase):
    def test_sshfs_remote_accepts_only_explicit_absolute_sources(self):
        for value in ('nas:/volume1/media', 'alice@nas.home:/home/alice',
                      'alias:/data with spaces', 'user@[2001:db8::1]:/srv/data'):
            self.assertEqual(FFP.validate_sshfs_remote(value), value)
        for value in ('', '-oProxyCommand=x:/data', 'nas:relative', 'user@-bad:/data',
                      'bad..host:/data', 'nas:/data\nHost:evil', 'nas:/data\x00'):
            with self.assertRaises(ValueError, msg=value):
                FFP.validate_sshfs_remote(value)

    def test_mount_parser_decodes_proc_escapes_and_marks_only_ffp_home_managed(self):
        mounts = '\n'.join((
            'nas:/data /mnt/ffp/home/root/media\\040share fuse.sshfs rw,nosuid 0 0',
            'other:/etc /etc/remote fuse.sshfs rw,nosuid 0 0',
            '/dev/sda1 /mnt/ffp/home/local ext4 rw 0 0'
        ))
        result = FFP.parse_sshfs_mounts(mounts, '/mnt/ffp')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['source'], 'nas:/data')
        self.assertEqual(result[0]['mountpoint'], '/ffp/home/root/media share')
        self.assertTrue(result[0]['manageable'])
        self.assertEqual(result[1]['mountpoint'], '/etc/remote')
        self.assertFalse(result[1]['manageable'])

    def test_mountpoint_must_be_normalized_and_below_ffp_home(self):
        self.assertEqual(
            FFP.ffp_home_mount_candidate('/ffp/home/root/mnt', '/mnt/ffp'),
            ('/ffp/home/root/mnt', '/mnt/ffp/home/root/mnt')
        )
        for path in ('/ffp', '/ffp/home', '/ffp/etc/ssh', '/ffp/home/root/../etc'):
            with self.assertRaises(ValueError, msg=path):
                FFP.ffp_home_mount_candidate(path, '/mnt/ffp')

    def test_sshd_candidate_is_checked_from_a_private_temp_file_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, 'sshd_config')
            observed = {}

            def fake_run(argv, timeout):
                self.assertEqual(argv[:3], ['/mock/sshd', '-t', '-f'])
                candidate = argv[3]
                self.assertEqual(os.path.dirname(candidate), directory)
                self.assertEqual(os.stat(candidate).st_mode & 0o777, 0o600)
                with open(candidate, 'rb') as handle:
                    observed['content'] = handle.read()
                observed['timeout'] = timeout
                return ''

            with mock.patch.object(FFP, 'run_fixed', side_effect=fake_run):
                FFP.validate_sshd_candidate(config, b'Port 2222\n', '/mock/sshd')
            self.assertEqual(observed['content'], b'Port 2222\n')
            self.assertEqual(observed['timeout'], 30)
            self.assertEqual(os.listdir(directory), [])

    def test_sshd_candidate_temp_is_removed_when_validator_rejects_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, 'sshd_config')
            with mock.patch.object(FFP, 'run_fixed', side_effect=RuntimeError('invalid directive')):
                with self.assertRaisesRegex(RuntimeError, 'invalid directive'):
                    FFP.validate_sshd_candidate(config, b'BadOption yes\n', '/mock/sshd')
            self.assertEqual(os.listdir(directory), [])

    def test_only_verified_ssh_config_files_get_extensionless_editor_access(self):
        with tempfile.TemporaryDirectory() as directory:
            server = os.path.join(directory, 'sshd_config')
            client = os.path.join(directory, 'ssh_config')
            with mock.patch.object(FFP, 'SSHD_CONFIG_PATH', server), \
                 mock.patch.object(FFP, 'SSH_CONFIG_PATH', client):
                self.assertTrue(FFP.is_text_editable_path(server))
                self.assertTrue(FFP.is_text_editable_path(client))
                self.assertTrue(FFP.is_managed_ssh_config(server))
                self.assertTrue(FFP.is_managed_ssh_config(client))
                self.assertFalse(FFP.is_managed_ssh_config(os.path.join(directory, 'other.conf')))
                self.assertFalse(FFP.is_text_editable_path(os.path.join(directory, 'id_rsa')))
                self.assertTrue(FFP.is_text_editable_path(os.path.join(directory, 'other.conf')))

    def test_atomic_write_preserves_existing_file_owner_group_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'ssh_config')
            with open(path, 'wb') as handle:
                handle.write(b'Host old\n')
            os.chmod(path, 0o640)
            before = os.stat(path)
            FFP.atomic_write(path, b'Host new\n', 0o640, (before.st_uid, before.st_gid))
            after = os.stat(path)
            self.assertEqual(after.st_uid, before.st_uid)
            self.assertEqual(after.st_gid, before.st_gid)
            self.assertEqual(after.st_mode & 0o777, 0o640)
            with open(path, 'rb') as handle:
                self.assertEqual(handle.read(), b'Host new\n')

    def test_sshfs_mount_options_are_tokenized_and_managed_options_are_reserved(self):
        self.assertEqual(
            FFP.validate_sshfs_mount_options('ServerAliveInterval=30, allow_other'),
            ['ServerAliveInterval=30', 'allow_other']
        )
        for value in ('reconnect', 'IdentityFile=/tmp/key', 'ssh_command=/bin/sh',
                      'ProxyCommand=/bin/touch', 'LocalCommand=id',
                      'allow_other,', 'Port=22', 'bad option', 'ProxyCommand=x\n'):
            with self.assertRaises(ValueError, msg=value):
                FFP.validate_sshfs_mount_options(value)

    def test_sshfs_identity_file_must_be_private_regular_file_under_home_ssh(self):
        with tempfile.TemporaryDirectory() as root:
            ssh_dir = os.path.join(root, 'home', 'root', '.ssh')
            os.makedirs(ssh_dir)
            key = os.path.join(ssh_dir, 'id_ed25519')
            with open(key, 'w') as handle:
                handle.write('private key')
            os.chmod(key, 0o600)
            with mock.patch.object(FFP, 'FILE_ROOT', root):
                self.assertEqual(FFP.validate_sshfs_identity_path(key), key)
                os.chmod(key, 0o644)
                with self.assertRaisesRegex(ValueError, 'permissions'):
                    FFP.validate_sshfs_identity_path(key)

    def test_sshfs_identity_file_rejects_symlinks_and_non_ssh_paths(self):
        with tempfile.TemporaryDirectory() as root:
            ssh_dir = os.path.join(root, 'home', 'root', '.ssh')
            os.makedirs(ssh_dir)
            target = os.path.join(ssh_dir, 'actual')
            with open(target, 'w') as handle:
                handle.write('private key')
            os.chmod(target, 0o600)
            link = os.path.join(ssh_dir, 'linked')
            os.symlink(target, link)
            with mock.patch.object(FFP, 'FILE_ROOT', root):
                with self.assertRaisesRegex(ValueError, 'Symlinked'):
                    FFP.validate_sshfs_identity_path(link)
                with self.assertRaisesRegex(ValueError, 'below'):
                    FFP.validate_sshfs_identity_path(os.path.join(root, 'home', 'root', 'key'))


if __name__ == '__main__':
    unittest.main()
