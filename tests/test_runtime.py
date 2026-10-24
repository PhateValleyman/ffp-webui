import importlib.machinery
import importlib.util
import io
import os
import socket
import socketserver
import unittest
from unittest import mock


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ffp', 'ffp', 'bin', 'ffp-webui')
LOADER = importlib.machinery.SourceFileLoader('ffp_webui_runtime_test_module', SCRIPT)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
FFP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(FFP)


class RuntimeTests(unittest.TestCase):
    def test_ip_discovery_reads_interfaces_without_dns(self):
        ifreq = bytearray(256)
        ifreq[20:24] = socket.inet_aton('192.168.1.20')
        original_open = open

        def fake_open(path, *args, **kwargs):
            if path == '/proc/net/if_inet6':
                return io.StringIO('')
            return original_open(path, *args, **kwargs)

        with mock.patch.object(FFP.socket, 'if_nameindex', return_value=[(2, 'eth0')]), \
             mock.patch.object(FFP.fcntl, 'ioctl', return_value=bytes(ifreq)), \
             mock.patch.object(FFP.socket, 'getaddrinfo', side_effect=AssertionError('DNS lookup attempted')), \
             mock.patch('builtins.open', side_effect=fake_open):
            self.assertEqual(FFP.local_ip_addresses(), ['192.168.1.20'])

    def test_server_uses_threading_http_server(self):
        self.assertTrue(issubclass(FFP.ThreadingHTTPServer, socketserver.ThreadingMixIn))

    def test_entrypoint_and_service_use_verified_static_python_shim(self):
        project = os.path.dirname(os.path.dirname(__file__))
        with open(SCRIPT, 'r', encoding='utf-8') as handle:
            self.assertEqual(handle.readline().strip(), '#!/ffp/opt/python-3.13-static/bin/python3.13')
            backend = handle.read()
        self.assertIn("os.environ.setdefault('SSL_CERT_FILE', '/ffp/opt/python-3.13-static/ssl/cert.pem')", backend)
        self.assertIn("'/ffp/bin/bash', '/ffp/opt/python-3.13-static/bin/python3.13'", backend)
        self.assertIn('from ffp_webui_rclone import RcloneBridge, normalize_remote_path', backend)
        build_path = os.path.join(project, 'build.sh')
        with open(build_path, 'r', encoding='utf-8') as handle:
            builder = handle.read()
        self.assertIn('ffp_webui_rclone.py" "$STAGE/ffp/bin/ffp_webui_rclone.py"', builder)
        service_path = os.path.join(project, 'ffp', 'ffp', 'start', 'ffp-webui.sh')
        with open(service_path, 'r', encoding='utf-8') as handle:
            service = handle.read()
        self.assertIn('WEBUI_PYTHON=/ffp/bin/python3.13-static', service)
        self.assertIn('import hashlib, math, ssl', service)
        self.assertIn('"$WEBUI_PYTHON" "$WEBUI_BIN" --config "$WEBUI_CONFIG"', service)


if __name__ == '__main__':
    unittest.main()
