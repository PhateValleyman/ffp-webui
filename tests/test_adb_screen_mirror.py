import importlib.machinery
import importlib.util
import io
import os
import struct
import threading
import unittest
import zlib
from types import SimpleNamespace
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPT = os.path.join(ROOT, 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_adb_screen_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)
SERIAL = '192.168.1.12:5555'


def png_chunk(kind, data):
    body = kind + data
    return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)


def small_png(width=320, height=240):
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    pixels = b'\x00' + b'\x00\x00\x00' * width
    raw = pixels * height
    return b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', header) + png_chunk(b'IDAT', zlib.compress(raw)) + png_chunk(b'IEND', b'')


class HttpRecorder:
    def __init__(self, app):
        self.server = SimpleNamespace(app=app)
        self.app = app
        self.wfile = io.BytesIO()
        self.status = None
        self.headers = {}
        self.query_one = lambda _name, default='': SERIAL if default == '' else default

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers[name] = value

    def end_headers(self):
        pass

    @property
    def body(self):
        return self.wfile.getvalue()


class AdbScreenValidationTests(unittest.TestCase):
    def test_coordinates_require_bounded_plain_integers(self):
        self.assertEqual(FFP.validate_adb_screen_coordinate(0), 0)
        self.assertEqual(FFP.validate_adb_screen_coordinate(16383), 16383)
        for value in (-1, 16384, True, 1.5, '3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FFP.validate_adb_screen_coordinate(value)


class AdbScreenCaptureTests(unittest.TestCase):
    def make_handler(self, demo=False):
        app = SimpleNamespace(demo=demo, adb_screen_lock=threading.Lock())
        handler = HttpRecorder(app)
        handler.adb_require_device = mock.Mock(return_value='/ffp/bin/adb')
        handler._error = lambda status, message: FFP.write_json(handler, status, {'error': message})
        return handler

    def test_capture_uses_bounded_exec_out_and_returns_png_without_disk_staging(self):
        handler = self.make_handler()
        image = small_png()
        with mock.patch.object(FFP, 'run_capture_limited', return_value=image) as capture:
            FFP.Handler.adb_screen_capture(handler)
        capture.assert_called_once_with(
            ['/ffp/bin/adb', '-s', SERIAL, 'exec-out', 'screencap', '-p'],
            12, FFP.ADB_SCREEN_MAX_BYTES, discard_stderr=True)
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.headers['Content-Type'], 'image/png')
        self.assertEqual(int(handler.headers['Content-Length']), len(image))
        self.assertEqual(handler.body, image)
        self.assertFalse(handler.server.app.adb_screen_lock.locked())

    def test_demo_mode_blocks_screenshot_capture(self):
        handler = self.make_handler(demo=True)
        with mock.patch.object(FFP, 'run_capture_limited') as capture:
            FFP.Handler.adb_screen_capture(handler)
        capture.assert_not_called()
        self.assertEqual(handler.status, 423)

    def test_capture_lock_rejects_parallel_frame(self):
        handler = self.make_handler()
        handler.server.app.adb_screen_lock.acquire()
        try:
            with mock.patch.object(FFP, 'run_capture_limited') as capture:
                FFP.Handler.adb_screen_capture(handler)
            capture.assert_not_called()
            self.assertEqual(handler.status, 429)
        finally:
            handler.server.app.adb_screen_lock.release()

    def test_invalid_png_is_rejected(self):
        handler = self.make_handler()
        invalid = b'not a png' + b'\x00' * 24
        with mock.patch.object(FFP, 'run_capture_limited', return_value=invalid):
            FFP.Handler.adb_screen_capture(handler)
        self.assertEqual(handler.status, 502)
        self.assertIn(b'invalid PNG', handler.body)


class AdbScreenInputTests(unittest.TestCase):
    def make_handler(self, request, demo=False):
        def read_json(_handler, limit):
            self.assertEqual(limit, 8192)
            return request
        app = SimpleNamespace(demo=demo, read_json=read_json, audit=mock.Mock())
        handler = HttpRecorder(app)
        handler.adb_require_device = mock.Mock(return_value='/ffp/bin/adb')
        handler._error = lambda status, message: FFP.write_json(handler, status, {'error': message})
        return handler

    def test_tap_and_swipe_use_only_validated_numeric_arguments(self):
        cases = [
            ({'serial': SERIAL, 'action': 'tap', 'x': 321, 'y': 654}, 'input tap 321 654'),
            ({'serial': SERIAL, 'action': 'swipe', 'x1': 1, 'y1': 2, 'x2': 300, 'y2': 400, 'duration_ms': 700}, 'input swipe 1 2 300 400 700'),
        ]
        for request, remote_command in cases:
            with self.subTest(action=request['action']):
                handler = self.make_handler(request)
                with mock.patch.object(FFP, 'run_fixed', return_value='') as run:
                    FFP.Handler.adb_screen_input(handler)
                run.assert_called_once_with(['/ffp/bin/adb', '-s', SERIAL, 'shell', remote_command], 8)
                self.assertEqual(handler.status, 200)
                self.assertTrue(handler.server.app.audit.called)

    def test_navigation_keycodes_are_allow_listed(self):
        for key, keycode in FFP.ADB_SCREEN_KEYCODES.items():
            with self.subTest(key=key):
                handler = self.make_handler({'serial': SERIAL, 'action': 'key', 'key': key})
                with mock.patch.object(FFP, 'run_fixed') as run:
                    FFP.Handler.adb_screen_input(handler)
                run.assert_called_once_with(['/ffp/bin/adb', '-s', SERIAL, 'shell', 'input keyevent ' + keycode], 8)
        handler = self.make_handler({'serial': SERIAL, 'action': 'key', 'key': 'KEYCODE_POWER'})
        with mock.patch.object(FFP, 'run_fixed') as run:
            FFP.Handler.adb_screen_input(handler)
        run.assert_not_called()
        self.assertEqual(handler.status, 400)

    def test_text_spaces_are_encoded_and_shell_metacharacters_quoted(self):
        handler = self.make_handler({'serial': SERIAL, 'action': 'text', 'text': 'hello world; echo nope'})
        with mock.patch.object(FFP, 'run_fixed') as run:
            FFP.Handler.adb_screen_input(handler)
        run.assert_called_once_with(
            ['/ffp/bin/adb', '-s', SERIAL, 'shell', "input text 'hello%sworld;%secho%snope'"], 8)
        self.assertEqual(handler.status, 200)

    def test_invalid_coordinates_duration_reserved_text_and_unhashable_key_are_rejected(self):
        requests = [
            {'serial': SERIAL, 'action': 'tap', 'x': '1; reboot', 'y': 2},
            {'serial': SERIAL, 'action': 'swipe', 'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1, 'duration_ms': 2000},
            {'serial': SERIAL, 'action': 'text', 'text': 'reserved %s sequence'},
            {'serial': SERIAL, 'action': 'key', 'key': []},
            {'serial': SERIAL, 'action': 'text', 'text': 'line\nfeed'},
        ]
        for request in requests:
            with self.subTest(request=request):
                handler = self.make_handler(request)
                with mock.patch.object(FFP, 'run_fixed') as run:
                    FFP.Handler.adb_screen_input(handler)
                run.assert_not_called()
                self.assertEqual(handler.status, 400)

    def test_demo_mode_blocks_all_device_input(self):
        handler = self.make_handler({'serial': SERIAL, 'action': 'key', 'key': 'home'}, demo=True)
        with mock.patch.object(FFP, 'run_fixed') as run:
            FFP.Handler.adb_screen_input(handler)
        run.assert_not_called()
        self.assertEqual(handler.status, 423)


class AdbScreenFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'internal', 'webui', 'assets', 'index.html'), encoding='utf-8') as handle:
            cls.html = handle.read()
        with open(os.path.join(ROOT, 'internal', 'webui', 'assets', 'app.js'), encoding='utf-8') as handle:
            cls.js = handle.read()
        with open(SCRIPT, encoding='utf-8') as handle:
            cls.backend = handle.read()

    def test_ui_exposes_stream_control_navigation_and_text(self):
        for item in ('adb-screen-device', 'adb-screen-start', 'adb-screen-stop', 'adb-screen-image', 'adb-screen-text-form'):
            with self.subTest(item=item):
                self.assertIn('id="%s"' % item, self.html)
        for action in ("action: 'tap'", "action: 'swipe'", "action: 'key'", "action: 'text'"):
            with self.subTest(action=action):
                self.assertIn(action, self.js)
        self.assertIn('document.hidden', self.js)
        self.assertIn("if (name !== 'adb') stopAdbScreen()", self.js)

    def test_routes_and_blob_csp_are_present(self):
        self.assertIn("path == '/api/adb/screen' and self.command == 'GET'", self.backend)
        self.assertIn("path == '/api/adb/screen/input' and self.command == 'POST'", self.backend)
        self.assertIn("img-src 'self' data: blob:", self.backend)
        self.assertIn("'exec-out', 'screencap', '-p'", self.backend)


if __name__ == '__main__':
    unittest.main()
