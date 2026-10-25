# Rclone Remote Control bridge for FFP WebUI (Python standard library only).
import json
import os
import posixpath
import re
import select
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from urllib.parse import urlsplit


REMOTE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
OPTION_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}$')


def _iso_now():
    return datetime.utcnow().isoformat() + 'Z'


def _safe_component(value):
    return (isinstance(value, str) and bool(value) and value not in ('.', '..') and
            len(value) <= 255 and '/' not in value and '\\' not in value and
            not any(ord(ch) < 32 or ord(ch) == 127 for ch in value))


def normalize_remote_path(raw):
    if not isinstance(raw, str) or len(raw) > 4096 or '\x00' in raw or '\\' in raw:
        raise ValueError('Invalid remote path')
    value = raw.strip('/')
    if not value:
        return ''
    parts = value.split('/')
    if any(part in ('', '.', '..') or len(part) > 255 or
           any(ord(ch) < 32 or ord(ch) == 127 for ch in part) for part in parts):
        raise ValueError('Invalid remote path component')
    return '/'.join(parts)


class RcloneBridge(object):
    """Owns a private rclone rcd process and exposes only narrow operations."""
    def __init__(self, backend, command_lookup, environment_factory, mount_reader):
        self.backend = backend
        self.command_lookup = command_lookup
        self.environment_factory = environment_factory
        self.mount_reader = mount_reader
        self.lock = threading.RLock()
        self.transfer_guard = threading.Lock()
        self.config_lock = threading.Lock()
        self.process = None
        self.port = None
        self.binary = None
        self.provider_cache = None
        self.provider_cache_time = 0
        self.config_sessions = {}
        self.jobs = {}
        self.job_order = []
        self.closed = False

    def _request(self, port, method, params=None, timeout=15):
        if not re.match(r'^[a-z][a-z0-9/]+$', method):
            raise ValueError('Unsupported rclone operation')
        body = json.dumps(params or {}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        request = urllib.request.Request('http://127.0.0.1:%d/%s' % (int(port), method),
                                         data=body, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read(65536)
                error_data = json.loads(raw.decode('utf-8', 'replace'))
                message = error_data.get('error', 'HTTP %s' % exc.code)
            except Exception:
                message = 'HTTP %s' % exc.code
            raise RuntimeError('rclone %s: %s' % (method, str(message)[:800]))
        except Exception as exc:
            raise RuntimeError('rclone %s is unavailable: %s' % (method, str(exc)[:300]))
        if len(raw) > 8 * 1024 * 1024:
            raise RuntimeError('rclone response exceeds the 8 MiB limit')
        try:
            result = json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:
            raise RuntimeError('rclone returned an invalid JSON response')
        if not isinstance(result, dict):
            raise RuntimeError('rclone returned an invalid response')
        return result

    def _allocate_port(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('127.0.0.1', 0))
            return int(sock.getsockname()[1])
        finally:
            sock.close()

    def _ensure_server(self):
        with self.lock:
            if self.closed:
                raise RuntimeError('rclone bridge is shutting down')
            if self.process is not None and self.process.poll() is None:
                try:
                    self._request(self.port, 'core/version', {}, timeout=2)
                    return
                except Exception:
                    try:
                        self.process.terminate()
                        self.process.wait(timeout=2)
                    except Exception:
                        try:
                            self.process.kill()
                        except Exception:
                            pass
                    self.process = None
                    self.port = None
            binary = self.command_lookup('rclone')
            if not binary:
                raise RuntimeError('rclone executable was not found in /ffp/bin or system PATH')
            port = self._allocate_port()
            argv = [binary, 'rcd', '--rc-addr=127.0.0.1:%d' % port, '--rc-no-auth']
            try:
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, env=self.environment_factory(),
                                        close_fds=True, cwd='/')
            except Exception as exc:
                raise RuntimeError('Could not start the local rclone RC service: %s' % str(exc)[:300])
            self.process, self.port, self.binary = proc, port, binary
            last_error = None
            for _ in range(50):
                if proc.poll() is not None:
                    self.process = None
                    raise RuntimeError('rclone rcd exited during startup (status %s)' % proc.returncode)
                try:
                    self._request(port, 'core/version', {}, timeout=1)
                    return
                except Exception as exc:
                    last_error = exc
                    time.sleep(0.1)
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self.process, self.port = None, None
            raise RuntimeError('rclone rcd did not become ready: %s' % str(last_error)[:300])

    def rc_call(self, method, params=None, timeout=20):
        self._ensure_server()
        return self._request(self.port, method, params, timeout)

    def close(self):
        with self.lock:
            self.closed = True
            proc = self.process
            self.process = None
            self.port = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass

    def status(self):
        try:
            version = self.rc_call('core/version', {})
            remotes = self.remote_names()
            return {'available': True, 'version': str(version.get('version', 'unknown'))[:80],
                    'remotes': len(remotes), 'note': 'RC je dostupné pouze přes loopback.'}
        except Exception as exc:
            return {'available': False, 'version': '', 'remotes': 0, 'error': str(exc)[:500]}

    def remote_names(self):
        data = self.rc_call('config/listremotes', {})
        remotes = data.get('remotes', [])
        if not isinstance(remotes, list):
            raise RuntimeError('rclone returned an invalid remote list')
        result = []
        for item in remotes:
            name = str(item).rstrip(':')
            if REMOTE_RE.fullmatch(name) and name not in result:
                result.append(name)
        result.sort(key=lambda value: value.lower())
        return result

    def remote_details(self):
        details = []
        for name in self.remote_names():
            remote_type = ''
            try:
                config = self.remote_config(name)
                remote_type = str(config.get('type', config.get('Type', ''))).lower()
            except Exception:
                pass
            details.append({'name': name, 'type': remote_type or 'unknown',
                            'kind': 'sftp' if remote_type == 'sftp' else 'rclone'})
        return details

    def remote_config(self, name):
        name = self._validate_remote(name)
        if name not in self.remote_names():
            raise ValueError('Configured rclone remote was not found')
        data = self.rc_call('config/get', {'name': name})
        config = data.get('config', data.get('Config', data))
        if isinstance(config, dict) and name in config and isinstance(config[name], dict):
            config = config[name]
        if not isinstance(config, dict):
            raise RuntimeError('rclone returned invalid remote configuration metadata')
        return config

    def sftp_connection(self, name):
        config = self.remote_config(name)
        if str(config.get('type', config.get('Type', ''))).lower() != 'sftp':
            raise ValueError('The selected rclone remote is not an SFTP remote')
        host = str(config.get('host', config.get('Host', '')))
        user = str(config.get('user', config.get('User', '')))
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:\-\[\]]{0,254}', host):
            raise ValueError('SFTP remote host is not a supported SSH destination')
        if user and not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', user):
            raise ValueError('SFTP remote username is not a supported SSH username')
        port_value = str(config.get('port', config.get('Port', '22')) or '22')
        if not port_value.isdigit() or not 1 <= int(port_value) <= 65535:
            raise ValueError('SFTP remote port is invalid')
        key_file = str(config.get('key_file', config.get('keyFile', '')) or '')
        root = str(config.get('root', config.get('_root', '')) or '')
        if root and (not root.startswith('/') or posixpath.normpath(root) != root or '..' in root.split('/')):
            raise ValueError('SFTP remote root is not a normalized absolute path')
        return {'target': (user + '@' if user else '') + host, 'port': int(port_value),
                'key_file': key_file, 'root': root}

    def providers(self, force=False):
        if self.provider_cache is not None and not force and time.time() - self.provider_cache_time < 60:
            return self.provider_cache
        data = self.rc_call('config/providers', {})
        raw_providers = data.get('providers', [])
        result = []
        if not isinstance(raw_providers, list):
            raise RuntimeError('rclone returned invalid provider metadata')
        for provider in raw_providers:
            if not isinstance(provider, dict):
                continue
            name = str(provider.get('Name', provider.get('name', '')))
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name):
                continue
            options = []
            for option in provider.get('Options', provider.get('options', [])):
                if not isinstance(option, dict):
                    continue
                key = str(option.get('Name', option.get('name', '')))
                hide = int(option.get('Hide', option.get('hide', 0)) or 0)
                if not OPTION_RE.fullmatch(key) or hide:
                    continue
                is_password = bool(option.get('IsPassword', option.get('isPassword', False)))
                is_sensitive = bool(option.get('Sensitive', option.get('sensitive', False)))
                default = option.get('DefaultStr', option.get('Default', option.get('default', '')))
                if is_password or is_sensitive:
                    default = ''
                examples = []
                for example in option.get('Examples', option.get('examples', [])) or []:
                    if isinstance(example, dict):
                        examples.append({'value': str(example.get('Value', example.get('value', ''))),
                                         'help': str(example.get('Help', example.get('help', '')))[:500]})
                options.append({'name': key, 'help': str(option.get('Help', option.get('help', '')))[:2000],
                                'type': str(option.get('Type', option.get('type', 'string'))).lower(),
                                'default': '' if default is None else str(default),
                                'required': bool(option.get('Required', option.get('required', False))),
                                'password': is_password,
                                'sensitive': is_sensitive,
                                'exclusive': bool(option.get('Exclusive', option.get('exclusive', False))),
                                'advanced': bool(option.get('Advanced', option.get('advanced', False))),
                                'examples': examples})
            result.append({'name': name,
                           'description': str(provider.get('Description', provider.get('description', '')))[:500],
                           'options': options})
        result.sort(key=lambda item: item['name'].lower())
        self.provider_cache = result
        self.provider_cache_time = time.time()
        return result

    def files(self, name, raw_path):
        name = self._validate_remote(name)
        path = normalize_remote_path(raw_path)
        if name not in self.remote_names():
            raise ValueError('Configured rclone remote was not found')
        data = self.rc_call('operations/list', {'fs': name + ':', 'remote': path,
                                                'opt': {'recurse': False}})
        raw_entries = data.get('list', data.get('List', []))
        if not isinstance(raw_entries, list):
            raise RuntimeError('rclone returned an invalid directory listing')
        entries = []
        for item in raw_entries[:10000]:
            if not isinstance(item, dict):
                continue
            rel = str(item.get('Path', item.get('path', '')))
            entry_name = str(item.get('Name', item.get('name', '')))
            if not entry_name and rel:
                entry_name = posixpath.basename(rel.rstrip('/'))
            if not _safe_component(entry_name):
                continue
            is_dir = bool(item.get('IsDir', item.get('isDir', False)))
            try:
                size = int(item.get('Size', item.get('size', 0)))
            except (TypeError, ValueError):
                size = 0
            modified = str(item.get('ModTime', item.get('modTime', '')) or '')
            rel_path = '/'.join(part for part in (path, entry_name) if part)
            entries.append({'name': entry_name, 'path': '/' + rel_path if rel_path else '/',
                            'directory': is_dir, 'regular': not is_dir, 'symlink': False,
                            'size': max(0, size), 'modified': modified, 'editable': False})
        entries.sort(key=lambda item: (not item['directory'], item['name'].lower()))
        return {'remote': name, 'path': '/' + path if path else '/',
                'parent': '/' + posixpath.dirname(path) if path and posixpath.dirname(path) else '',
                'entries': entries}

    def preview_bytes(self, name, raw_path, limit=32 * 1024 * 1024):
        name = self._validate_remote(name)
        path = normalize_remote_path(raw_path)
        if not path or name not in self.remote_names():
            raise ValueError('Invalid Rclone media path')
        basename = posixpath.basename(path)
        parent = posixpath.dirname(path)
        entry = next((item for item in self.files(name, parent)['entries']
                      if item['name'] == basename and not item['directory']), None)
        if entry is None:
            raise ValueError('Rclone preview path is not a regular file')
        if entry['size'] > limit:
            raise ValueError('Media file exceeds the 32 MiB preview limit')
        self._ensure_server()
        argv = [self.binary, 'cat', name + ':' + path]
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=self.environment_factory(),
                                close_fds=True, start_new_session=True)
        started = time.time()
        output, error = bytearray(), bytearray()
        open_streams = [proc.stdout, proc.stderr]
        try:
            while open_streams or proc.poll() is None:
                if time.time() - started > 90:
                    raise RuntimeError('Rclone media preview timed out')
                ready = select.select(open_streams, [], [], 0.1)[0] if open_streams else []
                for stream in ready:
                    chunk = os.read(stream.fileno(), 65536)
                    if not chunk:
                        open_streams.remove(stream)
                        continue
                    if stream is proc.stdout:
                        if len(output) + len(chunk) > limit:
                            raise RuntimeError('Rclone media preview exceeded the 32 MiB limit')
                        output.extend(chunk)
                    else:
                        error.extend(chunk)
                        if len(error) > 4096:
                            del error[:-4096]
            if proc.returncode != 0:
                raise RuntimeError('rclone cat failed: ' + error.decode('utf-8', 'replace')[-1000:])
            return bytes(output)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
            proc.wait()
            raise
        finally:
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except Exception:
                    pass

    def _validate_remote(self, name):
        if not isinstance(name, str) or not REMOTE_RE.fullmatch(name):
            raise ValueError('Invalid rclone remote name')
        return name

    def _provider(self, remote_type):
        for provider in self.providers():
            if provider['name'] == remote_type:
                return provider
        raise ValueError('Unknown rclone storage type')

    def _config_response(self, response, session=None):
        if not isinstance(response, dict):
            response = {}
        state = str(response.get('State', response.get('state', '')) or '')
        option = response.get('Option', response.get('option'))
        message = str(response.get('Error', response.get('error', '')) or '')[:1500]
        if state:
            if session is None:
                raise RuntimeError('rclone returned an incomplete configuration without a session')
            session['state'] = state
            sid = session['id']
            return {'complete': False, 'session_id': sid,
                    'option': self._sanitize_question(option), 'error': message}
        if session is not None:
            self.config_sessions.pop(session['id'], None)
        if message:
            return {'complete': False, 'error': message}
        return {'complete': True, 'remote': session['name'] if session else '',
                'action': session.get('operation', 'create') if session else 'create'}

    def _sanitize_question(self, option):
        if not isinstance(option, dict):
            return None
        is_password = bool(option.get('IsPassword', option.get('isPassword', False)))
        is_sensitive = bool(option.get('Sensitive', option.get('sensitive', False)))
        default = '' if is_password or is_sensitive else option.get('DefaultStr', option.get('Default', option.get('default', '')))
        examples = []
        for example in option.get('Examples', option.get('examples', [])) or []:
            if isinstance(example, dict):
                examples.append({'value': str(example.get('Value', example.get('value', ''))),
                                 'help': str(example.get('Help', example.get('help', '')))[:500]})
        return {'name': str(option.get('Name', option.get('name', 'answer')))[:100],
                'help': str(option.get('Help', option.get('help', '')))[:2000],
                'type': str(option.get('Type', option.get('type', 'string'))).lower(),
                'default': '' if default is None else str(default),
                'required': bool(option.get('Required', option.get('required', False))),
                'password': is_password or is_sensitive,
                'sensitive': is_sensitive,
                'exclusive': bool(option.get('Exclusive', option.get('exclusive', False))),
                'examples': examples}

    def _clean_provider_parameters(self, provider, parameters):
        if not isinstance(parameters, dict) or len(parameters) > 128:
            raise ValueError('Invalid provider fields')
        allowed = {option['name'] for option in provider['options']}
        clean = {}
        for key, value in parameters.items():
            if not isinstance(key, str) or not OPTION_RE.fullmatch(key) or key not in allowed:
                raise ValueError('Unsupported provider option: ' + str(key)[:80])
            if not isinstance(value, (str, int, bool, float)):
                raise ValueError('Provider values must be plain text')
            text = str(value)
            if len(text) > 8192 or '\x00' in text:
                raise ValueError('Provider value is too long or invalid')
            clean[key] = text
        return clean

    def remote_edit_profile(self, name):
        config = self.remote_config(name)
        remote_type = str(config.get('type', config.get('Type', '')))
        provider = self._provider(remote_type)
        values_by_key = {str(key).lower(): value for key, value in config.items()}
        values = {}
        secret_fields = []
        for option in provider['options']:
            key = option['name']
            if key.lower() not in values_by_key:
                continue
            value = values_by_key[key.lower()]
            if option.get('password') or option.get('sensitive'):
                if value not in (None, ''):
                    secret_fields.append(key)
                continue
            if isinstance(value, (str, int, bool, float)):
                values[key] = str(value)
        return {'name': name, 'type': remote_type, 'values': values,
                'secret_fields': secret_fields}

    def _start_remote_config(self, name, remote_type, parameters, operation):
        self._prune_config_sessions()
        if self.config_sessions:
            raise RuntimeError('Finish or cancel the other pending Rclone configuration first')
        self._validate_remote(name)
        provider = self._provider(remote_type)
        clean = self._clean_provider_parameters(provider, parameters)
        session = {'id': uuid.uuid4().hex, 'name': name, 'type': remote_type,
                   'parameters': clean, 'state': '', 'created': time.time(),
                   'operation': operation}
        method = 'config/update' if operation == 'update' else 'config/create'
        payload = {'name': name, 'parameters': clean, 'opt': {'nonInteractive': True}}
        if operation == 'create':
            payload['type'] = remote_type
        response = self.rc_call(method, payload)
        result = self._config_response(response, session)
        if not result.get('complete') and result.get('session_id'):
            self._prune_config_sessions()
            self.config_sessions[session['id']] = session
        return result

    def create_remote(self, request):
        if not isinstance(request, dict):
            raise ValueError('Invalid storage configuration request')
        name = request.get('name', '')
        remote_type = request.get('type', '')
        with self.config_lock:
            self._validate_remote(name)
            if self.transfer_guard.locked():
                raise RuntimeError('Wait for active Rclone transfers before adding a remote')
            if name in self.remote_names():
                raise ValueError('A remote with this name already exists')
            return self._start_remote_config(name, remote_type, request.get('parameters', {}), 'create')

    def update_remote(self, request):
        if not isinstance(request, dict):
            raise ValueError('Invalid storage configuration request')
        name = self._validate_remote(request.get('name', ''))
        if self.transfer_guard.locked():
            raise RuntimeError('Wait for active Rclone transfers before editing remote configuration')
        with self.config_lock:
            if self.transfer_guard.locked():
                raise RuntimeError('Wait for active Rclone transfers before editing remote configuration')
            if self.config_sessions:
                raise RuntimeError('Finish or cancel the pending Rclone configuration first')
            config = self.remote_config(name)
            remote_type = str(config.get('type', config.get('Type', '')))
            requested_type = request.get('type', remote_type)
            if requested_type != remote_type:
                raise ValueError('Changing a remote type is not supported; create a new remote instead')
            return self._start_remote_config(name, remote_type, request.get('parameters', {}), 'update')

    def delete_remote(self, request):
        if not isinstance(request, dict):
            raise ValueError('Invalid remote deletion request')
        name = self._validate_remote(request.get('name', ''))
        if request.get('confirm') != 'DELETE RCLONE REMOTE ' + name:
            raise ValueError('Exact remote deletion confirmation is required')
        if self.transfer_guard.locked():
            raise RuntimeError('Wait for active Rclone transfers before deleting a remote')
        with self.config_lock:
            if self.transfer_guard.locked():
                raise RuntimeError('Wait for active Rclone transfers before deleting a remote')
            if self.config_sessions:
                raise RuntimeError('Finish or cancel the pending Rclone configuration first')
            if name not in self.remote_names():
                raise ValueError('Configured rclone remote was not found')
            self.rc_call('config/delete', {'name': name})
        return {'ok': True, 'remote': name}

    def continue_remote(self, request):
        if not isinstance(request, dict):
            raise ValueError('Invalid configuration answer')
        sid = request.get('session_id', '')
        result = request.get('result', '')
        if not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{32}', sid):
            raise ValueError('Invalid configuration session')
        if not isinstance(result, (str, int, bool)) or len(str(result)) > 8192:
            raise ValueError('Invalid configuration answer')
        self._prune_config_sessions()
        session = self.config_sessions.get(sid)
        if session is None:
            raise ValueError('Configuration session expired or was cancelled')
        with self.config_lock:
            method = 'config/update' if session.get('operation') == 'update' else 'config/create'
            payload = {'name': session['name'], 'parameters': session['parameters'],
                       'opt': {'nonInteractive': True, 'continue': True,
                               'state': session['state'], 'result': str(result)}}
            if method == 'config/create':
                payload['type'] = session['type']
            response = self.rc_call(method, payload)
            return self._config_response(response, session)

    def _prune_config_sessions(self):
        now = time.time()
        for sid in list(self.config_sessions):
            if now - self.config_sessions[sid].get('created', now) > 900:
                self.config_sessions.pop(sid, None)
        while len(self.config_sessions) >= 10:
            oldest = min(self.config_sessions, key=lambda sid: self.config_sessions[sid].get('created', 0))
            self.config_sessions.pop(oldest, None)

    def cancel_remote(self, request):
        sid = request.get('session_id', '') if isinstance(request, dict) else ''
        removed = None
        if isinstance(sid, str):
            with self.config_lock:
                removed = self.config_sessions.pop(sid, None)
                no_pending = not self.config_sessions
            if removed and no_pending:
                try:
                    self.oauth_stop()
                except Exception:
                    pass
        return {'ok': True}

    def oauth_status(self):
        try:
            data = self.rc_call('config/oauthstatus', {})
        except RuntimeError as exc:
            message = str(exc).lower()
            if 'not found' in message or 'unknown method' in message or '404' in message:
                return {'supported': False, 'status': 'unsupported', 'auth_url': '',
                        'note': 'Tato verze rclone nemá config/oauthstatus; použijte OAuth token z rclone authorize.'}
            raise
        status = str(data.get('status', 'stopped')).lower()
        auth_url = str(data.get('authUrl', data.get('auth_url', '')) or '')
        if auth_url:
            parsed = urlsplit(auth_url)
            if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or not parsed.port:
                raise RuntimeError('rclone returned an unexpected OAuth callback URL')
        return {'supported': True, 'status': status if status in ('running', 'stopped') else 'unknown',
                'auth_url': auth_url, 'requires_loopback': bool(auth_url),
                'note': 'Loopback callback je dostupný jen lokálně nebo přes SSH tunel.'}

    def oauth_stop(self):
        status = self.oauth_status()
        if not status.get('supported') or status.get('status') != 'running':
            return {'stopped': False, 'supported': bool(status.get('supported'))}
        self.rc_call('config/oauthstop', {})
        return {'stopped': True, 'supported': True}

    def _descriptor(self, data):
        if not isinstance(data, dict):
            raise ValueError('Invalid panel source')
        kind = data.get('kind')
        if kind in ('rclone', 'sftp'):
            name = self._validate_remote(data.get('remote', ''))
            if name not in self.remote_names():
                raise ValueError('Configured rclone remote was not found')
            if kind == 'sftp':
                detail = next((item for item in self.remote_details() if item['name'] == name), None)
                if not detail or detail['kind'] != 'sftp':
                    raise ValueError('Selected SFTP remote is not configured with the SFTP backend')
            return {'kind': kind, 'remote': name, 'path': normalize_remote_path(data.get('path', '/'))}
        if kind not in ('nas', 'sshfs'):
            raise ValueError('Rclone transfers support NAS, SSHFS and rclone sources; use NAS as an ADB bridge')
        raw = data.get('path', '')
        if not isinstance(raw, str) or not raw.startswith('/'):
            raise ValueError('An absolute local path is required')
        if kind == 'nas':
            local = self.backend.secure_path(raw)
        else:
            mountpoint = data.get('mountpoint', '')
            matches = [mount for mount in self.mount_reader() if mount.get('manageable') and mount.get('mountpoint') == mountpoint]
            if not matches or not (raw == mountpoint or raw.startswith(mountpoint.rstrip('/') + '/')):
                raise ValueError('SSHFS mount is no longer active or path is outside the selected mount')
            local = self.backend.secure_path(raw)
        if not os.path.isdir(local):
            raise ValueError('Local panel path is not a directory')
        return {'kind': kind, 'path': local, 'logical_path': os.path.normpath(raw),
                'mountpoint': data.get('mountpoint', '') if kind == 'sshfs' else ''}

    def _panel_fs(self, panel, child=''):
        if panel['kind'] in ('rclone', 'sftp'):
            base = panel['remote'] + ':' + panel['path']
            if not child:
                return base
            return base + ('/' if panel['path'] else '') + child
        base = panel['path']
        return os.path.join(base, child) if child else base

    def start_copy(self, request):
        with self.config_lock:
            if self.config_sessions:
                raise RuntimeError('Finish or cancel the pending Rclone configuration first')
            if self.transfer_guard.locked():
                raise RuntimeError('Another rclone transfer is already running')
            return self._start_copy_locked(request)

    def _start_copy_locked(self, request):
        if not isinstance(request, dict):
            raise ValueError('Invalid copy request')
        source = self._descriptor(request.get('source'))
        destination = self._descriptor(request.get('destination'))
        items = request.get('items')
        if not isinstance(items, list) or not items or len(items) > 200:
            raise ValueError('Select between 1 and 200 items')
        phrase = 'RCLONE COPY %d' % len(items)
        if request.get('confirm') != phrase:
            raise ValueError('Exact Rclone copy confirmation required: ' + phrase)
        if source['kind'] in ('rclone', 'sftp') and destination['kind'] in ('rclone', 'sftp') and source['remote'] == destination['remote'] and source['path'] == destination['path']:
            raise ValueError('Source and destination are the same directory')
        if source['kind'] not in ('rclone', 'sftp') and destination['kind'] not in ('rclone', 'sftp') and source['path'] == destination['path']:
            raise ValueError('Source and destination are the same directory')
        tasks = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('Invalid selected item')
            name = item.get('name')
            if not _safe_component(name) or name in seen:
                raise ValueError('Selected item name is invalid or duplicated')
            seen.add(name)
            is_dir = bool(item.get('directory', False))
            if source['kind'] not in ('rclone', 'sftp'):
                full = self.backend.secure_path(os.path.join(source['logical_path'], name))
                try:
                    st = os.lstat(full)
                except OSError:
                    raise ValueError('A selected local item is no longer available')
                if os.path.islink(full) or not (os.path.isdir(full) or os.path.isfile(full)):
                    raise ValueError('Only regular files and directories can be copied')
                if bool(os.path.isdir(full)) != is_dir:
                    raise ValueError('Selected item type changed; refresh the panel')
                if source['kind'] not in ('rclone', 'sftp') and destination['kind'] not in ('rclone', 'sftp') and is_dir:
                    dst_logical = destination['logical_path']
                    source_logical = os.path.normpath(os.path.join(source['logical_path'], name))
                    if dst_logical == source_logical or dst_logical.startswith(source_logical.rstrip('/') + '/'):
                        raise ValueError('Destination cannot be inside a selected directory')
            if is_dir:
                method = 'sync/copy'
                params = {'srcFs': self._panel_fs(source, name), 'dstFs': self._panel_fs(destination, name),
                          '_async': True}
            else:
                method = 'operations/copyfile'
                params = {'srcFs': self._panel_fs(source), 'srcRemote': name,
                          'dstFs': self._panel_fs(destination), 'dstRemote': name, '_async': True}
            tasks.append({'method': method, 'params': params, 'name': name})
        if not self.transfer_guard.acquire(False):
            raise RuntimeError('Another rclone transfer is already running')
        jid = uuid.uuid4().hex[:24]
        job = {'id': jid, 'kind': 'rclone copy', 'state': 'running', 'total': len(tasks),
               'completed': 0, 'current': '', 'progress': {}, 'started_at': _iso_now()}
        with self.lock:
            self.jobs[jid] = job
            self.job_order.append(jid)
            while len(self.job_order) > 30:
                old = self.job_order.pop(0)
                if old != jid:
                    self.jobs.pop(old, None)
        thread = threading.Thread(target=self._copy_worker, args=(jid, tasks))
        thread.daemon = True
        thread.start()
        return dict(job)

    def _update_job(self, jid, **fields):
        with self.lock:
            job = self.jobs.get(jid)
            if job is not None:
                job.update(fields)

    def _copy_worker(self, jid, tasks):
        try:
            for index, task in enumerate(tasks):
                self._update_job(jid, current=task['name'], current_index=index + 1)
                response = self.rc_call(task['method'], task['params'], timeout=30)
                remote_id = response.get('jobid', response.get('jobId'))
                if remote_id is None:
                    raise RuntimeError('rclone did not return an asynchronous job ID')
                try:
                    remote_id = int(remote_id)
                except (TypeError, ValueError):
                    raise RuntimeError('rclone returned an invalid job ID')
                while True:
                    status = self.rc_call('job/status', {'jobid': remote_id}, timeout=15)
                    try:
                        stats = self.rc_call('core/stats', {}, timeout=5)
                    except Exception:
                        stats = {}
                    progress = {}
                    for key in ('bytes', 'totalBytes', 'speed', 'eta', 'transfers', 'totalTransfers', 'checks', 'errors'):
                        value = stats.get(key)
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            progress[key] = value
                    progress['job_finished'] = bool(status.get('finished', False))
                    self._update_job(jid, progress=progress)
                    if status.get('finished'):
                        if not status.get('success', True) or status.get('error'):
                            raise RuntimeError(str(status.get('error') or 'rclone transfer failed')[:1000])
                        break
                    time.sleep(1)
                with self.lock:
                    job = self.jobs.get(jid)
                    if job is not None:
                        job['completed'] = index + 1
                        job['progress'] = {}
            self._update_job(jid, state='completed', ended_at=_iso_now(), current='', output='Rclone copy completed')
        except Exception as exc:
            self._update_job(jid, state='failed', ended_at=_iso_now(), error=str(exc)[:1200])
        finally:
            self.transfer_guard.release()

    def job(self, jid):
        if not isinstance(jid, str) or not re.fullmatch(r'[a-fA-F0-9]{24}', jid):
            return None
        with self.lock:
            result = self.jobs.get(jid)
            return dict(result) if result is not None else None
