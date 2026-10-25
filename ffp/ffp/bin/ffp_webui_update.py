"""Safe GitHub release checking and verified FFP-WebUI package staging.

This module deliberately does not install packages or invoke funpkg. It only
checks the fixed public project release endpoint and stages a verified .txz.
"""
from __future__ import print_function

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

OWNER = 'PhateValleyman'
REPOSITORY = 'ffp-webui'
API_HOST = 'api.github.com'
API_PATH = '/repos/PhateValleyman/ffp-webui/releases/latest'
API_URL = 'https://api.github.com' + API_PATH
DOWNLOAD_HOSTS = frozenset(('github.com', 'release-assets.githubusercontent.com'))
VERSION_RE = re.compile(r'^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
DIGEST_RE = re.compile(r'^sha256:([A-Fa-f0-9]{64})$')
MAX_RELEASE_JSON = 262144
AUTO_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
ASSET_NAME_RE = re.compile(r'^ffp-webui-[0-9]+\.[0-9]+\.[0-9]+-python3\.13-static-UNVERIFIED\.txz$')
PARTIAL_NAME_RE = re.compile(r'^ffp-webui-[0-9]+\.[0-9]+\.[0-9]+-python3\.13-static-UNVERIFIED\.txz\.part-[a-f0-9]{32}$')
SHA256_RE = re.compile(r'^[a-f0-9]{64}$')


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, ip, timeout):
        http.client.HTTPSConnection.__init__(self, host, port=443, timeout=timeout,
                                             context=ssl.create_default_context())
        self.pinned_ip = ip

    def connect(self):
        sock = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _public_ip(value):
    address = ipaddress.ip_address(value.split('%', 1)[0])
    if (address.is_private or address.is_loopback or address.is_link_local or
            address.is_multicast or address.is_reserved or address.is_unspecified):
        return False
    if isinstance(address, ipaddress.IPv4Address):
        for network in ('100.64.0.0/10', '192.0.0.0/24', '192.0.2.0/24',
                        '198.18.0.0/15', '198.51.100.0/24', '203.0.113.0/24',
                        '240.0.0.0/4'):
            if address in ipaddress.ip_network(network):
                return False
    return True


def _resolve_public(host):
    try:
        rows = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)
    except Exception:
        raise ValueError('GitHub host could not be resolved')
    addresses = []
    for row in rows:
        address = row[4][0].split('%', 1)[0]
        try:
            if not _public_ip(address):
                raise ValueError('GitHub host resolved to a non-public address')
        except (OSError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError('GitHub host resolved to an invalid address')
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ValueError('GitHub host has no public address')
    return addresses


def _validated_url(raw, allowed_hosts):
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except Exception:
        raise ValueError('GitHub returned an invalid HTTPS URL')
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.fragment or (port is not None and port != 443) or
            parsed.hostname.lower() not in allowed_hosts):
        raise ValueError('GitHub returned a URL outside the allowed HTTPS hosts')
    return parsed


def _open_response(url, allowed_hosts, headers, timeout=12):
    parsed = _validated_url(url, allowed_hosts)
    host = parsed.hostname.lower()
    request_path = parsed.path or '/'
    if parsed.query:
        request_path += '?' + parsed.query
    last_error = None
    for address in _resolve_public(host):
        connection = None
        try:
            connection = PinnedHTTPSConnection(host, address, timeout)
            connection.request('GET', request_path, headers=headers)
            response = connection.getresponse()
            return connection, response
        except Exception as exc:
            last_error = exc
            if connection is not None:
                connection.close()
    raise ValueError('GitHub HTTPS request failed: ' + str(last_error or 'no public address')[:180])


def _read_json_api():
    connection, response = _open_response(API_URL, frozenset((API_HOST,)), {
        'User-Agent': 'FFP-WebUI/' + __name__,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Connection': 'close',
    })
    try:
        if response.status != 200:
            if response.status == 403:
                raise ValueError('GitHub API is rate-limited or unavailable')
            raise ValueError('GitHub release API returned HTTP ' + str(response.status))
        length = response.getheader('Content-Length')
        if length:
            try:
                metadata_size = int(length)
            except ValueError:
                raise ValueError('GitHub returned an invalid metadata size')
            if metadata_size < 0 or metadata_size > MAX_RELEASE_JSON:
                raise ValueError('GitHub release metadata is too large or invalid')
        data = response.read(MAX_RELEASE_JSON + 1)
        if len(data) > MAX_RELEASE_JSON:
            raise ValueError('GitHub release metadata is too large')
        try:
            value = json.loads(data.decode('utf-8'))
        except Exception:
            raise ValueError('GitHub release metadata is not valid JSON')
        if not isinstance(value, dict):
            raise ValueError('GitHub release metadata has an invalid shape')
        return value
    finally:
        response.close()
        connection.close()


def _version_tuple(value):
    match = VERSION_RE.match(value if isinstance(value, str) else '')
    if not match:
        raise ValueError('Release tag is not a stable vMAJOR.MINOR.PATCH version')
    return tuple(int(part) for part in match.groups())


def parse_release(document, current_version, max_package_bytes=268435456):
    """Validate a GitHub latest-release document and return a safe asset record."""
    if not isinstance(document, dict) or document.get('draft') is not False or document.get('prerelease') is not False:
        raise ValueError('Only published stable GitHub releases are supported')
    tag = document.get('tag_name')
    remote_version = _version_tuple(tag)
    current = _version_tuple('v' + current_version)
    filename = 'ffp-webui-' + tag[1:] + '-python3.13-static-UNVERIFIED.txz'
    assets = document.get('assets')
    if not isinstance(assets, list):
        raise ValueError('GitHub release assets are missing')
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get('name') == filename]
    if len(matches) != 1:
        raise ValueError('Release does not contain exactly one expected FFP installer')
    asset = matches[0]
    if asset.get('state') != 'uploaded':
        raise ValueError('GitHub installer asset is not fully uploaded')
    digest_match = DIGEST_RE.match(asset.get('digest', '') if isinstance(asset.get('digest'), str) else '')
    if not digest_match:
        raise ValueError('GitHub does not provide a SHA-256 digest for this installer')
    size = asset.get('size')
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > max_package_bytes:
        raise ValueError('GitHub installer size is invalid or exceeds the configured limit')
    expected_asset_url = 'https://github.com/' + OWNER + '/' + REPOSITORY + '/releases/download/' + tag + '/' + filename
    if asset.get('browser_download_url') != expected_asset_url:
        raise ValueError('GitHub installer URL does not match the expected release asset')
    expected_release_url = 'https://github.com/' + OWNER + '/' + REPOSITORY + '/releases/tag/' + tag
    if document.get('html_url') != expected_release_url:
        raise ValueError('GitHub release URL does not match the expected repository')
    published_at = document.get('published_at')
    if not isinstance(published_at, str) or not published_at:
        raise ValueError('GitHub release is not published')
    notes = document.get('body', '')
    if not isinstance(notes, str):
        notes = ''
    notes = notes[:4000]
    return {
        'version': tag[1:],
        'tag': tag,
        'newer': remote_version > current,
        'release_url': expected_release_url,
        'asset_name': filename,
        'asset_url': expected_asset_url,
        'sha256': digest_match.group(1).lower(),
        'size': size,
        'published_at': document.get('published_at', '') if isinstance(document.get('published_at'), str) else '',
        'notes': notes,
    }


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_stale_partials(packages_dir):
    try:
        names = os.listdir(packages_dir)
    except OSError:
        return
    for name in names:
        if not PARTIAL_NAME_RE.fullmatch(name):
            continue
        path = os.path.join(packages_dir, name)
        try:
            if stat.S_ISREG(os.lstat(path).st_mode):
                os.unlink(path)
        except OSError:
            pass


def _download_verified(asset, destination, max_package_bytes):
    os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(destination), 0o700)
    if os.path.lexists(destination):
        if os.path.islink(destination) or not os.path.isfile(destination):
            raise ValueError('Existing update staging path is not a regular file')
        if os.path.getsize(destination) > max_package_bytes:
            raise ValueError('Existing staged update exceeds the configured size limit')
        digest = hashlib.sha256()
        with open(destination, 'rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
        if digest.hexdigest() != asset['sha256']:
            raise ValueError('A different package with this release name already exists in staging')
        return destination

    temp_path = destination + '.part-' + uuid.uuid4().hex
    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    hasher = hashlib.sha256()
    total = 0
    try:
        url = asset['asset_url']
        for redirect_count in range(6):
            connection, response = _open_response(url, DOWNLOAD_HOSTS, {
                'User-Agent': 'FFP-WebUI-release-updater/1',
                'Accept': 'application/octet-stream',
                'Connection': 'close',
            }, timeout=20)
            try:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    if not location or redirect_count >= 5:
                        raise ValueError('GitHub asset redirect is missing or excessive')
                    next_url = urljoin(url, location)
                    _validated_url(next_url, DOWNLOAD_HOSTS)
                    url = next_url
                    continue
                if response.status != 200:
                    raise ValueError('GitHub installer download returned HTTP ' + str(response.status))
                length = response.getheader('Content-Length')
                if length:
                    try:
                        content_size = int(length)
                    except ValueError:
                        raise ValueError('GitHub installer has an invalid content length')
                    if content_size < 0 or content_size > max_package_bytes:
                        raise ValueError('GitHub installer exceeds the configured size limit')
                with os.fdopen(fd, 'wb') as output:
                    fd = None
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_package_bytes:
                            raise ValueError('GitHub installer exceeds the configured size limit')
                        hasher.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                break
            finally:
                response.close()
                connection.close()
        else:
            raise ValueError('GitHub installer redirect limit exceeded')
        if total != asset['size'] or hasher.hexdigest() != asset['sha256']:
            raise ValueError('GitHub installer size or SHA-256 digest does not match release metadata')
        os.chmod(temp_path, 0o600)
        if os.path.lexists(destination):
            raise ValueError('Update package appeared in staging during download')
        os.rename(temp_path, destination)
        return destination
    except Exception:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


class GitHubSelfUpdater(object):
    """Automatically check and stage verified FFP-WebUI releases; never install."""
    def __init__(self, current_version, state_root, max_package_bytes=268435456,
                 interval_seconds=AUTO_CHECK_INTERVAL_SECONDS):
        self.current_version = current_version
        self.state_root = state_root
        self.packages_dir = os.path.join(self.state_root, 'packages')
        self.max_package_bytes = max_package_bytes
        self.interval_seconds = max(3600, int(interval_seconds))
        self._state_lock = threading.Lock()
        self._check_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        _remove_stale_partials(self.packages_dir)
        self._state = {
            'current_version': current_version,
            'state': 'waiting',
            'automatic_check': True,
            'interval_hours': int(self.interval_seconds // 3600),
            'latest_version': '',
            'release_url': '',
            'asset_name': '',
            'staged_path': '',
            'sha256': '',
            'last_checked_at': '',
            'error': '',
            'notes': '',
        }

    def status(self):
        with self._state_lock:
            return dict(self._state)

    def verified_install_target(self):
        snapshot = self.status()
        if snapshot.get('state') != 'available':
            raise ValueError('No verified GitHub update is available')
        asset_name = snapshot.get('asset_name')
        if not isinstance(asset_name, str) or not ASSET_NAME_RE.fullmatch(asset_name):
            raise ValueError('Verified GitHub asset name is invalid')
        path = snapshot.get('staged_path')
        expected_path = os.path.join(self.packages_dir, asset_name)
        if not isinstance(path, str) or os.path.abspath(path) != os.path.abspath(expected_path):
            raise ValueError('Verified GitHub asset is outside its staging path')
        expected_digest = snapshot.get('sha256')
        if not isinstance(expected_digest, str) or not SHA256_RE.fullmatch(expected_digest):
            raise ValueError('Verified GitHub asset digest is unavailable')
        st = os.lstat(expected_path)
        if not stat.S_ISREG(st.st_mode) or st.st_size <= 0 or st.st_size > self.max_package_bytes:
            raise ValueError('Verified GitHub asset is no longer a regular staged package')
        if _sha256_file(expected_path) != expected_digest:
            raise ValueError('Verified GitHub asset digest changed after staging')
        return {'asset_name': asset_name, 'path': expected_path, 'sha256': expected_digest}

    def check_now(self):
        if not self._check_lock.acquire(False):
            return self.status()
        with self._state_lock:
            self._state.update({'state': 'checking', 'error': ''})
        try:
            record = parse_release(_read_json_api(), self.current_version, self.max_package_bytes)
            staged = ''
            state = 'current'
            if record['newer']:
                staged = _download_verified(
                    record,
                    os.path.join(self.packages_dir, record['asset_name']),
                    self.max_package_bytes,
                )
                state = 'available'
            result = {
                'current_version': self.current_version,
                'state': state,
                'automatic_check': True,
                'interval_hours': int(self.interval_seconds // 3600),
                'latest_version': record['version'],
                'release_url': record['release_url'],
                'asset_name': record['asset_name'] if staged else '',
                'staged_path': staged,
                'sha256': record['sha256'] if staged else '',
                'last_checked_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                'error': '',
                'notes': record['notes'],
            }
        except Exception as exc:
            result = self.status()
            result.update({
                'state': 'error',
                'last_checked_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                'error': str(exc)[:300],
            })
        finally:
            self._check_lock.release()
        with self._state_lock:
            self._state = result
            return dict(self._state)

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='ffp-webui-release-check', daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            self.check_now()
            if self._stop.wait(self.interval_seconds):
                return

    def close(self):
        self._stop.set()
