import importlib.machinery
import importlib.util
import os
import subprocess
import tempfile
import unittest
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)


class AccountValidationTests(unittest.TestCase):
    def setUp(self):
        self.handler = object()

    def test_login_is_strict_and_rejects_newline(self):
        for value in ('alice', 'svc_1', '_user-2'):
            self.assertEqual(FFP.Handler.account_login(self.handler, value), value)
        for value in ('', 'Root', '-alice', 'a' * 33, 'alice\n', 'alice:admin'):
            with self.assertRaises(ValueError):
                FFP.Handler.account_login(self.handler, value)

    def test_comment_rejects_passwd_delimiters_and_linebreaks(self):
        self.assertEqual(FFP.Handler.account_comment(self.handler, 'Jan Novák'), 'Jan Novák')
        for value in ('x:y', 'x\ny', 'x\ry', '-option', 'x' * 201):
            with self.assertRaises(ValueError):
                FFP.Handler.account_comment(self.handler, value)

    def test_home_requires_managed_existing_parent_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as outside:
            snapshot = {'home_bases': [base]}
            allowed = os.path.join(base, 'alice')
            self.assertEqual(FFP.Handler.account_home(self.handler, allowed, snapshot), allowed)
            with self.assertRaises(ValueError):
                FFP.Handler.account_home(self.handler, os.path.join(base, '..', 'escape'), snapshot)
            link = os.path.join(base, 'shortcut')
            os.symlink(outside, link)
            with self.assertRaises(ValueError):
                FFP.Handler.account_home(self.handler, os.path.join(link, 'alice'), snapshot)

    def test_group_ids_accept_only_configured_ids(self):
        snapshot = {'groups': [{'gid': 500}, {'gid': 501}]}
        self.assertEqual(FFP.Handler.account_group_ids(self.handler, ['500', 501, '500'], snapshot), [500, 501])
        for values in (['99'], ['bad'], '500', [True]):
            with self.assertRaises(ValueError):
                FFP.Handler.account_group_ids(self.handler, values, snapshot)

    def test_password_algorithm_follows_target_login_defs(self):
        self.assertEqual(FFP.effective_password_algorithm({'encrypt_method': 'sha512', 'md5_crypt_enab': 'YES'}), 'SHA512')
        self.assertEqual(FFP.effective_password_algorithm({'md5_crypt_enab': 'yes'}), 'MD5')
        self.assertEqual(FFP.effective_password_algorithm({}), 'DES')


class PasswordInputTests(unittest.TestCase):
    def test_secret_is_sent_only_on_stdin_and_mutable_buffer_is_wiped(self):
        captured = {}

        class FakeProcess:
            returncode = 0

            def communicate(self, payload=None, timeout=None):
                captured['stdin'] = bytes(payload)
                captured['timeout'] = timeout
                return b'', None

        def fake_popen(argv, **kwargs):
            captured['argv'] = list(argv)
            captured['kwargs'] = kwargs
            return FakeProcess()

        secret = bytearray(b'alice:example-password\n')
        with mock.patch.object(FFP.subprocess, 'Popen', side_effect=fake_popen):
            self.assertTrue(FFP.run_secret_input(['/ffp/sbin/chpasswd'], secret, 60))
        self.assertEqual(captured['argv'], ['/ffp/sbin/chpasswd'])
        self.assertEqual(captured['stdin'], b'alice:example-password\n')
        self.assertEqual(secret, bytearray(len(secret)))
        self.assertIs(captured['kwargs']['stdin'], subprocess.PIPE)

    def test_process_creation_failure_wipes_secret_buffer(self):
        secret = bytearray(b'alice:secret\n')
        with mock.patch.object(FFP.subprocess, 'Popen', side_effect=OSError('unavailable')):
            with self.assertRaisesRegex(OSError, 'unavailable'):
                FFP.run_secret_input(['/ffp/sbin/chpasswd'], secret, 1)
        self.assertEqual(secret, bytearray(len(secret)))

    def test_timeout_wipes_secret_buffer(self):
        class FakeProcess:
            returncode = -9

            def __init__(self):
                self.calls = 0
                self.killed = False

            def communicate(self, payload=None, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired(['chpasswd'], timeout)
                return b'', None

            def kill(self):
                self.killed = True

        process = FakeProcess()
        secret = bytearray(b'alice:secret\n')
        with mock.patch.object(FFP.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                FFP.run_secret_input(['/ffp/sbin/chpasswd'], secret, 1)
        self.assertTrue(process.killed)
        self.assertEqual(secret, bytearray(len(secret)))


if __name__ == '__main__':
    unittest.main()
