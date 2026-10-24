import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_terminal_adb_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)


class AdbValidationTests(unittest.TestCase):
    def test_endpoint_requires_host_and_valid_port(self):
        self.assertEqual(FFP.validate_adb_endpoint('192.168.1.50:5555'), '192.168.1.50:5555')
        self.assertEqual(FFP.validate_adb_endpoint('[::1]:5555'), '[::1]:5555')
        for value in ('192.168.1.1:0', '192.168.1.1:65536', 'host', 'host:5;id', 'host:1\n'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FFP.validate_adb_endpoint(value)

    def test_serial_and_remote_path_are_constrained(self):
        self.assertEqual(FFP.validate_adb_serial('ZX1A2B3C'), 'ZX1A2B3C')
        for serial in ('', 'serial with spaces', 'abc;id', 'x' * 129):
            with self.subTest(serial=serial), self.assertRaises(ValueError):
                FFP.validate_adb_serial(serial)
        self.assertEqual(FFP.validate_adb_remote_path('/sdcard/Download'), '/sdcard/Download')
        for path in ('relative', '/sdcard/../system', '/sdcard/./x', '/sdcard//x', '/sdcard/\x00'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                FFP.validate_adb_remote_path(path)

    def test_pairing_code_is_written_to_subprocess_stdin(self):
        code = bytearray(b'123456\n')
        result = FFP.run_capture(
            [sys.executable, '-c', 'import sys; print(sys.stdin.readline().strip())'],
            5, code)
        self.assertEqual(result, '123456')


class AdbRebootTests(unittest.TestCase):
    def test_each_reboot_mode_uses_a_fixed_command_and_exact_device_confirmation(self):
        expected_args = {
            'system': ['/ffp/bin/adb', '-s', 'ZX1A2B3C', 'reboot'],
            'recovery': ['/ffp/bin/adb', '-s', 'ZX1A2B3C', 'reboot', 'recovery'],
            'bootloader': ['/ffp/bin/adb', '-s', 'ZX1A2B3C', 'reboot', 'bootloader'],
            'fastboot': ['/ffp/bin/adb', '-s', 'ZX1A2B3C', 'reboot', 'fastboot'],
        }
        for mode, expected in expected_args.items():
            with self.subTest(mode=mode):
                req = {'serial': 'ZX1A2B3C', 'mode': mode,
                       'confirm': 'REBOOT %s ZX1A2B3C' % mode.upper()}
                start_job = mock.Mock(return_value={'id': 'reboot-job'})
                app = SimpleNamespace(read_json=lambda _handler, _limit: req,
                                      start_job=start_job, audit=mock.Mock())
                handler = object.__new__(FFP.Handler)
                handler.server = SimpleNamespace(app=app)
                handler.adb_require_device = mock.Mock(return_value='/ffp/bin/adb')
                with mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)), \
                     mock.patch.object(FFP, 'run_fixed', return_value='sent') as run:
                    status, body = handler.adb_reboot_device()
                    _description, operation = start_job.call_args.args
                    output = operation()
                self.assertEqual(status, 202)
                self.assertEqual(body['id'], 'reboot-job')
                run.assert_called_once_with(expected, 30)
                self.assertIn('ADB reboot requested: %s on ZX1A2B3C' % mode, output)

    def test_invalid_mode_is_rejected_before_device_operation(self):
        req = {'serial': 'ZX1A2B3C', 'mode': 'shell', 'confirm': 'REBOOT SHELL ZX1A2B3C'}
        handler = object.__new__(FFP.Handler)
        handler.server = SimpleNamespace(app=SimpleNamespace(read_json=lambda _handler, _limit: req))
        handler._error = mock.Mock(return_value='rejected')
        result = handler.adb_reboot_device()
        self.assertEqual(result, 'rejected')
        handler._error.assert_called_once_with(400, 'Allowed reboot modes: system, recovery, bootloader, fastboot')


class AdbCopyTests(unittest.TestCase):
    def test_cross_panel_copy_uses_confirmed_pull_and_push(self):
        with tempfile.TemporaryDirectory() as directory:
            local = os.path.join(directory, 'copy.tmp')
            with open(local, 'wb') as handle:
                handle.write(b'abc')
            req = {'serial': 'ZX1A2B3C', 'source': '/sdcard/A.txt', 'destination': '/sdcard/backup/A.txt',
                   'confirm': 'COPY /sdcard/A.txt -> /sdcard/backup/A.txt'}
            start_job = mock.Mock(return_value={'id': 'copy-job'})
            audit = mock.Mock()
            handler = object.__new__(FFP.Handler)
            handler.server = SimpleNamespace(app=SimpleNamespace(
                read_json=lambda _handler, _limit: req,
                cfg={'max_upload_bytes': 1024},
                start_job=start_job,
                audit=audit,
            ))
            handler.adb_require_device = mock.Mock(return_value='/ffp/bin/adb')
            handler.adb_pull_file = mock.Mock(return_value=(local, 3))
            with mock.patch.object(FFP, 'write_json', side_effect=lambda _h, status, body: (status, body)), \
                 mock.patch.object(FFP, 'run_fixed', return_value='push ok') as run:
                status, body = handler.adb_file_copy()
                kind, operation = start_job.call_args.args
                output = operation()
            self.assertEqual(status, 202)
            self.assertEqual(body['id'], 'copy-job')
            self.assertEqual(kind, 'ADB copy /sdcard/A.txt -> /sdcard/backup/A.txt')
            handler.adb_pull_file.assert_called_once_with('/ffp/bin/adb', 'ZX1A2B3C', '/sdcard/A.txt', 1024)
            run.assert_called_once_with(['/ffp/bin/adb', '-s', 'ZX1A2B3C', 'push', local, '/sdcard/backup/A.txt'], 300)
            self.assertIn('Copied 3 bytes', output)
            self.assertFalse(os.path.exists(local))

    def test_cross_panel_copy_rejects_missing_confirmation(self):
        req = {'serial': 'ZX1A2B3C', 'source': '/sdcard/A.txt', 'destination': '/sdcard/B.txt', 'confirm': ''}
        handler = object.__new__(FFP.Handler)
        handler.server = SimpleNamespace(app=SimpleNamespace(read_json=lambda _handler, _limit: req))
        handler._error = mock.Mock(return_value='rejected')
        result = handler.adb_file_copy()
        self.assertEqual(result, 'rejected')
        handler._error.assert_called_once_with(400, 'Exact remote file-copy confirmation required')


class TerminalSessionTests(unittest.TestCase):
    def test_local_terminal_context_tracks_the_process_working_directory(self):
        with tempfile.TemporaryDirectory() as working_directory:
            session = FFP.TerminalSession(
                [sys.executable, '-c', 'import os,sys,time; os.chdir(sys.argv[1]); time.sleep(5)', working_directory],
                dict(os.environ), tempfile.gettempdir(), 'local', context={'source': 'nas', 'cwd': '/'})
            try:
                end = time.time() + 2
                context = {}
                while time.time() < end:
                    context = session.read(0)['context']
                    if context.get('cwd') == working_directory:
                        break
                    time.sleep(0.02)
                self.assertEqual(context['cwd'], working_directory)
            finally:
                session.close()

    def test_pty_session_accepts_input_and_returns_output(self):
        manager = FFP.TerminalManager()
        sid = manager.start(
            [sys.executable, '-c', 'import sys; print("ready", flush=True); print("got:" + sys.stdin.readline().strip(), flush=True)'],
            dict(os.environ), tempfile.gettempdir(), 'local')
        try:
            session = manager.get(sid)
            end = time.time() + 2
            output = ''
            while time.time() < end and 'ready' not in output:
                output += session.read(0)['data']
                time.sleep(0.02)
            session.write('hello\n')
            end = time.time() + 2
            while time.time() < end and 'got:hello' not in output:
                data = session.read(len(output))
                output += data['data']
                time.sleep(0.02)
            self.assertIn('ready', output)
            self.assertIn('got:hello', output)
        finally:
            manager.close(sid)
        self.assertEqual(manager.sessions, {})


if __name__ == '__main__':
    unittest.main()
