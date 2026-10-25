# Luanti server management helpers for the FFP WebUI (Python standard library only).
from __future__ import print_function

import ipaddress
import grp
import json
import os
import pwd
import re
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone

NAME_RE = re.compile(r'^[A-Za-z0-9._-]{1,128}$')
PLAYER_RE = re.compile(r'^[A-Za-z0-9_-]{1,20}$')
CONF_KEY_RE = re.compile(r'^[A-Za-z0-9_.]+$')
SECRET_KEY_RE = re.compile(r'(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)', re.I)
CATEGORY_FIELDS = {
    'games': 'games_path',
    'worlds': 'worlds_path',
    'mods': 'mods_path',
    'skins': 'skins_path',
    'userdata': 'user_path',
}
MAX_CONFIG_BYTES = 2 << 20
MAX_ARCHIVE_BYTES = 512 << 20
MAX_ARCHIVE_FILES = 5000
MAX_ARCHIVE_MEMBER = 256 << 20
SECRET_MASK = '********'


def valid_name(value):
    return bool(isinstance(value, str) and NAME_RE.match(value) and value not in ('.', '..') and '..' not in value)


def valid_bind_address(value):
    if not isinstance(value, str) or len(value) > 255 or any(ch in value for ch in '\x00\r\n '):
        raise ValueError('Bind address must be an IP address or empty for all interfaces')
    if value:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            raise ValueError('Bind address must be an IPv4/IPv6 address or empty')
    return value


def parse_conf(text):
    values = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        key = key.strip()
        if CONF_KEY_RE.match(key):
            values[key] = value.strip()
    return values


def mask_conf_secrets(text):
    result = []
    for line in text.splitlines():
        match = re.match(r'^(\s*)([A-Za-z0-9_]+)(\s*=\s*)(.*?)(\s*)$', line)
        if match and SECRET_KEY_RE.search(match.group(2)) and match.group(4):
            line = match.group(1) + match.group(2) + match.group(3) + SECRET_MASK + match.group(5)
        result.append(line)
    return '\n'.join(result) + ('\n' if text.endswith('\n') else '')


def restore_masked_secrets(new_text, old_text):
    old_values = {}
    for line in old_text.splitlines():
        match = re.match(r'^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$', line)
        if match and SECRET_KEY_RE.search(match.group(1)):
            old_values[match.group(1)] = match.group(2)
    result = []
    for line in new_text.splitlines():
        match = re.match(r'^(\s*)([A-Za-z0-9_]+)(\s*=\s*)(.*?)(\s*)$', line)
        if match and SECRET_KEY_RE.search(match.group(2)) and match.group(4) == SECRET_MASK:
            if match.group(2) not in old_values:
                raise ValueError('A masked secret has no existing value to preserve')
            line = match.group(1) + match.group(2) + match.group(3) + old_values[match.group(2)] + match.group(5)
        result.append(line)
    return '\n'.join(result) + ('\n' if new_text.endswith('\n') else '')


def _write_atomic(path, data, mode=0o600):
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.luanti-', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), mode)
        os.replace(temp, path)
        try:
            dfd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


class LuantiManager(object):
    def __init__(self, state_root='/ffp/var/ffp-webui', preferences_path='/ffp/etc/ffp-webui/luanti.json', demo=False, find_binary=None):
        self.state_root = os.path.normpath(state_root)
        self.preferences_path = os.path.normpath(preferences_path)
        self.demo = bool(demo)
        self.lock = threading.RLock()
        self.process = None
        self.preferences = self._defaults(find_binary)
        if not self.demo:
            self._load_preferences()
            os.makedirs(self._luanti_state(), mode=0o700, exist_ok=True)
            os.chmod(self._luanti_state(), 0o700)

    def _defaults(self, find_binary):
        def first_file(candidates):
            for path in candidates:
                if os.path.isfile(path) and not os.path.islink(path):
                    return path
            return candidates[0]
        def first_dir(candidates):
            for path in candidates:
                if os.path.isdir(path) and not os.path.islink(path):
                    return path
            return candidates[0]
        binary = first_file(['/ffp/bin/luantiserver', '/ffp/bin/minetestserver', '/ffp/bin/luanti', '/ffp/bin/minetest'])
        if find_binary:
            for name in ('luantiserver', 'minetestserver', 'luanti', 'minetest'):
                found = find_binary(name)
                if found and os.path.isfile(found) and os.access(found, os.X_OK):
                    binary = found
                    break
        return {
            'binary_path': binary,
            'config_path': first_file(['/ffp/etc/minetest.conf', '/ffp/etc/luanti/minetest.conf', '/ffp/share/minetest/minetest.conf']),
            'games_path': first_dir(['/ffp/share/luanti/games', '/ffp/share/minetest/games', '/ffp/games']),
            'worlds_path': first_dir(['/ffp/var/luanti/worlds', '/ffp/var/minetest/worlds', '/ffp/worlds']),
            'mods_path': first_dir(['/ffp/share/luanti/mods', '/ffp/share/minetest/mods', '/ffp/mods']),
            'skins_path': first_dir(['/ffp/share/luanti/skins', '/ffp/share/minetest/skins', '/ffp/skins']),
            'user_path': first_dir(['/ffp/var/luanti/user', '/ffp/var/minetest/user']),
            'run_as_user': '',
            'selected_world': '',
            'port': 30000,
            'bind_address': '',
        }

    def _luanti_state(self):
        return os.path.join(self.state_root, 'luanti')

    def _pid_path(self):
        return os.path.join(self._luanti_state(), 'server.json')

    def _log_path(self):
        return os.path.join(self._luanti_state(), 'server.log')

    def _backup_dir(self):
        return os.path.join(self._luanti_state(), 'backups')

    def _load_preferences(self):
        try:
            with open(self.preferences_path, 'r', encoding='utf-8') as source:
                supplied = json.load(source)
            if not isinstance(supplied, dict):
                return
            merged = dict(self.preferences)
            merged.update(supplied)
            self.preferences = self._validate_preferences(merged)
        except (OSError, ValueError, TypeError):
            # A malformed preferences file must not prevent the whole WebUI from starting.
            return

    def _validate_preferences(self, values):
        result = dict(self.preferences)
        for field in ('binary_path', 'config_path', 'games_path', 'worlds_path', 'mods_path', 'skins_path', 'user_path'):
            raw = values.get(field, result[field])
            result[field] = self.validate_path(raw, allow_missing=True, allow_root=False)
        data_roots = [(field, result[field]) for field in ('games_path', 'worlds_path', 'mods_path', 'skins_path', 'user_path')]
        for index, (field, path) in enumerate(data_roots):
            for other_field, other in data_roots[index + 1:]:
                try:
                    common = os.path.commonpath([path, other])
                except ValueError:
                    continue
                if common == path or common == other:
                    raise ValueError('Luanti data paths may not overlap: %s and %s' % (field, other_field))
        selected = values.get('selected_world', '')
        if selected and not valid_name(selected):
            raise ValueError('Invalid selected world name')
        result['selected_world'] = selected
        run_as_user = values.get('run_as_user', result.get('run_as_user', ''))
        if not isinstance(run_as_user, str) or len(run_as_user) > 64 or (run_as_user and not re.match(r'^[A-Za-z0-9_.-]{1,64}$', run_as_user)):
            raise ValueError('Invalid Luanti service account name')
        result['run_as_user'] = run_as_user
        port = values.get('port', result['port'])
        if isinstance(port, bool):
            raise ValueError('Port must be a number between 1 and 65535')
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise ValueError('Port must be a number between 1 and 65535')
        if port < 1 or port > 65535:
            raise ValueError('Port must be a number between 1 and 65535')
        result['port'] = port
        result['bind_address'] = valid_bind_address(values.get('bind_address', result['bind_address']))
        return result

    def validate_path(self, raw, allow_missing=True, allow_root=False):
        if not isinstance(raw, str) or not raw or len(raw) > 2048 or '\x00' in raw or not os.path.isabs(raw):
            raise ValueError('Use an absolute path up to 2048 characters')
        clean = os.path.normpath(raw)
        if not allow_root and clean == '/':
            raise ValueError('The root directory cannot be used as a Luanti path')
        if clean == self.state_root or clean.startswith(self.state_root.rstrip(os.sep) + os.sep):
            raise ValueError('Luanti data paths may not overlap WebUI internal state')
        current = os.path.sep
        missing = False
        for part in clean.strip(os.path.sep).split(os.path.sep):
            if not part:
                continue
            current = os.path.join(current, part)
            try:
                st = os.lstat(current)
            except OSError:
                missing = True
                continue
            if missing:
                raise ValueError('Path contains an existing component below a missing parent')
            if stat.S_ISLNK(st.st_mode):
                raise ValueError('Symlinked Luanti paths are not accepted')
        if not allow_missing and not os.path.exists(clean):
            raise ValueError('Path does not exist')
        return clean

    def _save_preferences(self, values):
        self.preferences = self._validate_preferences(values)
        if not self.demo:
            # Refuse symlinked preference paths even though this file is outside user-managed roots.
            parent = os.path.dirname(self.preferences_path)
            os.makedirs(parent, mode=0o700, exist_ok=True)
            if os.path.islink(parent) or os.path.islink(self.preferences_path):
                raise ValueError('Luanti preferences path may not be a symlink')
            _write_atomic(self.preferences_path, json.dumps(self.preferences, sort_keys=True, indent=2).encode('utf-8') + b'\n', 0o600)
        return dict(self.preferences)

    def update_paths(self, values):
        if not isinstance(values, dict):
            raise ValueError('Path settings object is required')
        allowed = set(('binary_path', 'config_path', 'games_path', 'worlds_path', 'mods_path', 'skins_path', 'user_path', 'run_as_user', 'selected_world'))
        updated = dict(self.preferences)
        for key, value in values.items():
            if key not in allowed:
                raise ValueError('Unknown Luanti path setting')
            updated[key] = value
        if values.get('run_as_user'):
            self._account_entry(values['run_as_user'])
        return self._save_preferences(updated)

    def _account_entry(self, name):
        if not isinstance(name, str) or not name:
            raise ValueError('Choose an existing non-root Luanti service account')
        try:
            entry = pwd.getpwnam(name)
        except KeyError:
            raise ValueError('The selected Luanti service account does not exist')
        if entry.pw_uid <= 0:
            raise ValueError('Luanti must run as an existing non-root account')
        groups = set([entry.pw_gid])
        try:
            groups.update(group.gr_gid for group in grp.getgrall() if name in group.gr_mem)
        except Exception:
            pass
        if 0 in groups:
            raise ValueError('Luanti service account may not belong to the root group')
        return entry, groups

    def run_as_users(self):
        result = []
        for entry in pwd.getpwall():
            if entry.pw_uid <= 0:
                continue
            try:
                self._account_entry(entry.pw_name)
            except ValueError:
                continue
            result.append({'name': entry.pw_name, 'uid': entry.pw_uid, 'home': entry.pw_dir})
        return sorted(result, key=lambda item: (item['name'].lower(), item['uid']))

    def _account_access(self, path, entry, groups, needed):
        clean = os.path.normpath(path)
        components = clean.strip(os.sep).split(os.sep) if clean != os.sep else []
        current = os.sep
        for index, part in enumerate(components):
            current = os.path.join(current, part)
            st = os.lstat(current)
            if stat.S_ISLNK(st.st_mode):
                raise ValueError('Luanti service paths may not contain symlinks')
            final = index == len(components) - 1
            if not final or stat.S_ISDIR(st.st_mode):
                required = 1  # execute/search permission on each parent directory
                if final:
                    required = needed
            else:
                required = needed
            if st.st_uid == entry.pw_uid:
                bits = (st.st_mode >> 6) & 7
            elif st.st_gid in groups:
                bits = (st.st_mode >> 3) & 7
            else:
                bits = st.st_mode & 7
            if bits & required != required:
                raise ValueError('Luanti service account lacks required access to %s' % path)

    def prepare_selected_world(self):
        if self.is_running():
            raise ValueError('Stop the Luanti server before changing world ownership')
        name = self.preferences.get('run_as_user', '')
        entry, _groups = self._account_entry(name)
        world_name = self.preferences.get('selected_world', '')
        if not world_name:
            raise ValueError('Select a world before preparing its ownership')
        root = self._item_path('worlds', world_name)
        visited = 0
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            for child in list(dirs):
                path = os.path.join(current, child)
                if os.path.islink(path):
                    dirs.remove(child)
                    continue
                os.chown(path, entry.pw_uid, entry.pw_gid)
                visited += 1
            os.chown(current, entry.pw_uid, entry.pw_gid)
            visited += 1
            for child in files:
                path = os.path.join(current, child)
                if os.path.islink(path):
                    continue
                os.chown(path, entry.pw_uid, entry.pw_gid)
                visited += 1
            if visited > 50000:
                raise ValueError('World ownership preparation stopped at the 50,000-entry safety limit')
        return {'world': world_name, 'owner': name, 'entries': visited}

    def read_config(self):
        path = self.validate_path(self.preferences['config_path'], allow_missing=True)
        if not os.path.exists(path):
            text = '# Luanti server configuration\nport = %d\nbind_address = %s\n' % (self.preferences['port'], self.preferences['bind_address'])
        else:
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_CONFIG_BYTES:
                raise ValueError('Luanti config must be a regular file up to 2 MiB')
            with open(path, 'r', encoding='utf-8', errors='replace') as source:
                text = source.read(MAX_CONFIG_BYTES + 1)
            if len(text.encode('utf-8')) > MAX_CONFIG_BYTES:
                raise ValueError('Luanti config exceeds 2 MiB')
        values = parse_conf(text)
        try:
            port = int(values.get('port', self.preferences['port']))
            if port < 1 or port > 65535:
                port = self.preferences['port']
        except (ValueError, TypeError):
            port = self.preferences['port']
        bind = values.get('bind_address', self.preferences['bind_address'])
        try:
            bind = valid_bind_address(bind)
        except ValueError:
            bind = self.preferences['bind_address']
        return {'content': mask_conf_secrets(text), 'port': port, 'bind_address': bind,
                'has_secrets': any(SECRET_KEY_RE.search(key) for key in values)}

    def save_config(self, content, port, bind_address, backup_callback=None):
        if self.is_running():
            raise ValueError('Stop the Luanti server before changing its configuration')
        if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_CONFIG_BYTES or '\x00' in content:
            raise ValueError('Luanti config must be UTF-8 text up to 2 MiB')
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise ValueError('Port must be a number between 1 and 65535')
        if port < 1 or port > 65535:
            raise ValueError('Port must be a number between 1 and 65535')
        bind_address = valid_bind_address(bind_address)
        path = self.validate_path(self.preferences['config_path'], allow_missing=True)
        if os.path.exists(path):
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_CONFIG_BYTES:
                raise ValueError('Luanti config must be a regular file up to 2 MiB')
            old = open(path, 'r', encoding='utf-8', errors='replace').read()
            if backup_callback:
                backup_callback(path, 'luanti-config')
        else:
            old = ''
        content = restore_masked_secrets(content, old)
        for key, value in parse_conf(content).items():
            if key == 'secure.enable_security' and value.lower() in ('false', 'no', '0'):
                raise ValueError('Luanti mod security may not be disabled from the WebUI')
        lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if '=' in stripped and not stripped.startswith('#'):
                key = stripped.split('=', 1)[0].strip()
                if key in ('port', 'bind_address'):
                    continue
            lines.append(line)
        lines.extend(['port = %d' % port, 'bind_address = %s' % bind_address])
        data = ('\n'.join(lines).rstrip() + '\n').encode('utf-8')
        parent = os.path.dirname(path)
        os.makedirs(parent, mode=0o755, exist_ok=True)
        if os.path.islink(parent) or os.path.islink(path):
            raise ValueError('Luanti config path may not be a symlink')
        _write_atomic(path, data, 0o600)
        self.preferences['port'] = port
        self.preferences['bind_address'] = bind_address
        self._save_preferences(self.preferences)
        self._set_auth_owner(path)
        return {'path': path, 'port': port, 'bind_address': bind_address, 'bytes': len(data)}

    def _category_root(self, category, create=False):
        field = CATEGORY_FIELDS.get(category)
        if not field:
            raise ValueError('Unknown Luanti item category')
        root = self.validate_path(self.preferences[field], allow_missing=True)
        if create:
            os.makedirs(root, mode=0o755, exist_ok=True)
        if os.path.exists(root) and not os.path.isdir(root):
            raise ValueError('Configured category path is not a directory')
        return root

    def list_category(self, category):
        root = self._category_root(category)
        if not os.path.isdir(root):
            return []
        try:
            names = sorted(os.listdir(root), key=lambda x: x.lower())
        except OSError:
            return []
        result = []
        for name in names:
            if not valid_name(name):
                continue
            path = os.path.join(root, name)
            try:
                st = os.lstat(path)
                if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) or category == 'userdata' and stat.S_ISREG(st.st_mode)):
                    continue
                entry = {'name': name, 'kind': 'directory' if stat.S_ISDIR(st.st_mode) else 'file',
                         'size': st.st_size if stat.S_ISREG(st.st_mode) else None,
                         'modified': int(st.st_mtime), 'has_readme': False}
                if stat.S_ISDIR(st.st_mode):
                    entry['has_readme'] = any(os.path.isfile(os.path.join(path, candidate)) and not os.path.islink(os.path.join(path, candidate)) for candidate in ('README.md', 'REDADME.md'))
                    if category == 'worlds':
                        entry['gameid'] = self.world_game_id(name)
                    elif category == 'games':
                        entry['title'] = self.game_title(name) or name
                    elif category == 'mods':
                        entry['title'] = self.mod_title(name) or name
                        entry['enabled'] = self.mod_enabled(name)
                result.append(entry)
            except OSError:
                continue
        return result

    def _item_path(self, category, name, require_dir=True):
        if not valid_name(name):
            raise ValueError('Invalid Luanti item name')
        root = self._category_root(category)
        path = self.validate_path(os.path.join(root, name), allow_missing=False)
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode) or (require_dir and not stat.S_ISDIR(st.st_mode)):
            raise ValueError('Luanti item must be a regular directory')
        return path

    def _read_text(self, path, limit=1 << 20):
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise ValueError('Luanti metadata file is not a regular file within size limits')
        with open(path, 'r', encoding='utf-8', errors='replace') as source:
            return source.read(limit + 1)

    def world_game_id(self, world_name):
        try:
            path = self._item_path('worlds', world_name)
            values = parse_conf(self._read_text(os.path.join(path, 'world.mt'), 1 << 20))
            game_id = values.get('gameid', '')
            return game_id if valid_name(game_id) else ''
        except (OSError, ValueError):
            return ''

    def game_title(self, game_id):
        try:
            path = self._item_path('games', game_id)
            values = parse_conf(self._read_text(os.path.join(path, 'game.conf'), 1 << 20))
            return values.get('title') or values.get('name') or ''
        except (OSError, ValueError):
            return ''

    def mod_title(self, mod_name):
        try:
            path = self._item_path('mods', mod_name)
            values = parse_conf(self._read_text(os.path.join(path, 'mod.conf'), 1 << 20))
            return values.get('name') or mod_name
        except (OSError, ValueError):
            return mod_name

    def _world_conf(self, world_name):
        world_path = self._item_path('worlds', world_name)
        conf_path = os.path.join(world_path, 'world.mt')
        if os.path.exists(conf_path):
            text = self._read_text(conf_path, 1 << 20)
        else:
            text = ''
        return world_path, conf_path, text

    def create_world(self, name, game_id):
        if self.is_running():
            raise ValueError('Stop the Luanti server before creating or changing worlds')
        if not valid_name(name) or not valid_name(game_id):
            raise ValueError('World and game names may contain only letters, digits, dot, underscore and hyphen')
        game_path = self._item_path('games', game_id)
        root = self._category_root('worlds', create=True)
        target = os.path.join(root, name)
        if os.path.lexists(target):
            raise FileExistsError('A world with this name already exists')
        os.mkdir(target, 0o755)
        try:
            data = ('gameid = %s\n' % game_id).encode('utf-8')
            self._write_world_file(os.path.join(target, 'world.mt'), data)
            run_as = self.preferences.get('run_as_user', '')
            if run_as:
                entry, _groups = self._account_entry(run_as)
                os.chown(target, entry.pw_uid, entry.pw_gid)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        prefs = dict(self.preferences)
        prefs['selected_world'] = name
        self._save_preferences(prefs)
        return {'name': name, 'gameid': game_id, 'path': target, 'created': True}

    def set_world_game(self, world_name, game_id):
        if self.is_running():
            raise ValueError('Stop the Luanti server before changing a world game')
        self._item_path('games', game_id)
        _world, conf_path, text = self._world_conf(world_name)
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if '=' in stripped and not stripped.startswith('#') and stripped.split('=', 1)[0].strip() == 'gameid':
                continue
            lines.append(line)
        lines.append('gameid = %s' % game_id)
        self._write_world_file(conf_path, ('\n'.join(lines).rstrip() + '\n').encode('utf-8'))
        prefs = dict(self.preferences)
        prefs['selected_world'] = world_name
        self._save_preferences(prefs)
        return {'world': world_name, 'gameid': game_id}

    def toggle_mod(self, name, enabled):
        if self.is_running():
            raise ValueError('Stop the Luanti server before changing world mods')
        if not valid_name(name) or not isinstance(enabled, bool):
            raise ValueError('A mod name and boolean enabled value are required')
        world_name = self.preferences.get('selected_world', '')
        if not world_name:
            raise ValueError('Select a world before changing mods')
        self._item_path('worlds', world_name)
        # A mod must be present in the configured global mod path or in this world's worldmods directory.
        global_mod = os.path.join(self._category_root('mods'), name)
        world_mod = os.path.join(self._item_path('worlds', world_name), 'worldmods', name)
        if not (os.path.isdir(global_mod) and not os.path.islink(global_mod) or os.path.isdir(world_mod) and not os.path.islink(world_mod)):
            raise ValueError('Mod is not installed in the configured mod path or selected world')
        world_path, conf_path, text = self._world_conf(world_name)
        key = 'load_mod_' + name
        lines = [line for line in text.splitlines() if not ('=' in line and not line.strip().startswith('#') and line.split('=', 1)[0].strip() == key)]
        lines.append('%s = %s' % (key, 'true' if enabled else 'false'))
        self._write_world_file(conf_path, ('\n'.join(lines).rstrip() + '\n').encode('utf-8'))
        return {'name': name, 'enabled': enabled, 'world': world_name}

    def read_readme(self, category, name):
        root = self._item_path(category, name)
        for filename in ('README.md', 'REDADME.md'):
            path = os.path.join(root, filename)
            if os.path.lexists(path):
                if os.path.islink(path):
                    raise ValueError('README may not be a symlink')
                text = self._read_text(path, 1 << 20)
                if len(text.encode('utf-8')) > (1 << 20):
                    raise ValueError('README exceeds 1 MiB')
                return {'kind': category, 'name': name, 'filename': filename, 'content': text}
        raise FileNotFoundError('README.md or REDADME.md was not found')

    def _source_children(self, source):
        names = os.listdir(source)
        if not names:
            raise ValueError('Archive contains no installable directory')
        if len(names) != 1 or not os.path.isdir(os.path.join(source, names[0])) or os.path.islink(os.path.join(source, names[0])):
            raise ValueError('Import archive must contain exactly one top-level directory')
        return os.path.join(source, names[0])

    def import_archive(self, category, name, archive_path):
        if self.is_running():
            raise ValueError('Stop the Luanti server before importing or installing content')
        if not valid_name(name):
            raise ValueError('Invalid Luanti item name')
        if category == 'userdata':
            raise ValueError('Bulk user-data import is disabled; restore a world backup through Worlds')
        root = self._category_root(category, create=True)
        target = os.path.join(root, name)
        if os.path.lexists(target):
            raise FileExistsError('An item with this name already exists; import never overwrites')
        st = os.lstat(archive_path)
        if not stat.S_ISREG(st.st_mode) or st.st_size <= 0 or st.st_size > MAX_ARCHIVE_BYTES:
            raise ValueError('Import archive must be a regular file up to 512 MiB')
        temporary = tempfile.mkdtemp(prefix='.luanti-import-', dir=root)
        try:
            self._extract_archive_safe(archive_path, temporary)
            payload = self._source_children(temporary)
            os.rename(payload, target)
            run_as = self.preferences.get('run_as_user', '')
            if run_as and category in ('worlds', 'games', 'mods'):
                entry, _groups = self._account_entry(run_as)
                for current, dirs, files in os.walk(target, topdown=True, followlinks=False):
                    os.chown(current, entry.pw_uid, entry.pw_gid)
                    for child in dirs + files:
                        path = os.path.join(current, child)
                        if not os.path.islink(path):
                            os.chown(path, entry.pw_uid, entry.pw_gid)
            return {'name': name, 'kind': category, 'path': target, 'installed': True}
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _extract_archive_safe(self, archive_path, destination):
        root = os.path.realpath(destination)
        created_files, created_dirs = [], []
        count, expanded = 0, 0

        def parts_for(name):
            if not isinstance(name, str) or not name or name.startswith('/') or re.match(r'^[A-Za-z]:', name) or '\\' in name or '\x00' in name or any(part == '..' for part in name.split('/')):
                raise ValueError('Archive contains an unsafe path')
            parts = [part for part in name.split('/') if part not in ('', '.')]
            if not parts or len(parts) > 64 or any(len(p) > 255 for p in parts):
                raise ValueError('Archive path is too long or empty')
            return parts

        def ensure_dirs(parts):
            current = root
            for part in parts:
                current = os.path.join(current, part)
                if os.path.lexists(current):
                    info = os.lstat(current)
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                        raise ValueError('Archive directory conflicts with an existing path')
                else:
                    os.mkdir(current, 0o755)
                    created_dirs.append(current)
            return current

        def write_file(name, source, size, mode):
            nonlocal expanded
            parts = parts_for(name)
            if size < 0 or size > MAX_ARCHIVE_MEMBER:
                raise ValueError('Archive member exceeds size limits')
            expanded += size
            if expanded > MAX_ARCHIVE_BYTES:
                raise ValueError('Expanded archive exceeds 512 MiB')
            parent = ensure_dirs(parts[:-1])
            target = os.path.join(parent, parts[-1])
            if os.path.lexists(target):
                raise ValueError('Archive contains duplicate paths')
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode & 0o755)
            created_files.append(target)
            copied = 0
            with os.fdopen(fd, 'wb') as output:
                while True:
                    chunk = source.read(65536)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > size or copied > MAX_ARCHIVE_MEMBER:
                        raise ValueError('Archive member exceeds declared size')
                    output.write(chunk)
                if copied != size:
                    raise ValueError('Archive member size does not match header')
                output.flush()
                os.fsync(output.fileno())
                os.fchmod(output.fileno(), mode & 0o755)

        try:
            is_zip = zipfile.is_zipfile(archive_path)
            if is_zip:
                archive = zipfile.ZipFile(archive_path, 'r')
                with archive:
                    if len(archive.infolist()) > MAX_ARCHIVE_FILES:
                        raise ValueError('Archive exceeds the 5,000-entry limit')
                    for info in archive.infolist():
                        count += 1
                        if count > MAX_ARCHIVE_FILES:
                            raise ValueError('Archive exceeds the 5,000-entry limit')
                        parts = parts_for(info.filename)
                        mode = (info.external_attr >> 16) & 0xffff
                        kind = stat.S_IFMT(mode)
                        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                            raise ValueError('Archive links and special files are not accepted')
                        if info.is_dir() or kind == stat.S_IFDIR:
                            ensure_dirs(parts)
                        else:
                            with archive.open(info, 'r') as source:
                                write_file(info.filename, source, info.file_size, (mode & 0o777) or 0o644)
            else:
                with tarfile.open(archive_path, mode='r|*') as archive:
                    for member in archive:
                        count += 1
                        if count > MAX_ARCHIVE_FILES:
                            raise ValueError('Archive exceeds the 5,000-entry limit')
                        parts = parts_for(member.name)
                        if member.isdir():
                            ensure_dirs(parts)
                        elif member.isfile():
                            source = archive.extractfile(member)
                            if source is None:
                                raise ValueError('Archive member could not be read')
                            with source:
                                write_file(member.name, source, member.size, member.mode & 0o777)
                        else:
                            raise ValueError('Archive links and special files are not accepted')
            if not created_dirs and not created_files:
                raise ValueError('Archive contains no installable files')
        except Exception:
            for path in reversed(created_files):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            for path in reversed(created_dirs):
                try:
                    os.rmdir(path)
                except OSError:
                    pass
            raise

    def backup_item(self, category, name):
        if self.is_running():
            raise ValueError('Stop the Luanti server before creating a consistent backup')
        source = self._item_path(category, name, require_dir=(category != 'userdata'))
        os.makedirs(self._backup_dir(), mode=0o700, exist_ok=True)
        archive_name = '%s-%s-%s.tar.gz' % (category, name, datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        archive_path = os.path.join(self._backup_dir(), archive_name)
        if os.path.lexists(archive_path):
            archive_name = '%s-%s-%s-%s.tar.gz' % (category, name, datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'), uuid.uuid4().hex[:8])
            archive_path = os.path.join(self._backup_dir(), archive_name)
        count, expanded = 0, 0
        try:
            with tarfile.open(archive_path, 'w:gz') as archive:
                source_stat = os.lstat(source)
                if stat.S_ISREG(source_stat.st_mode):
                    count, expanded = 1, source_stat.st_size
                    if expanded > MAX_ARCHIVE_BYTES:
                        raise ValueError('Backup exceeds the 512 MiB content limit')
                    archive.add(source, arcname=name, recursive=False)
                else:
                    for current, dirs, files in os.walk(source, topdown=True, followlinks=False):
                        dirs[:] = sorted([d for d in dirs if not os.path.islink(os.path.join(current, d))])
                        rel_dir = os.path.relpath(current, source)
                        arc_dir = name if rel_dir == '.' else name + '/' + rel_dir.replace(os.sep, '/')
                        if rel_dir != '.':
                            archive.add(current, arcname=arc_dir, recursive=False)
                            count += 1
                        for filename in sorted(files):
                            path = os.path.join(current, filename)
                            if os.path.islink(path):
                                continue
                            st = os.lstat(path)
                            if not stat.S_ISREG(st.st_mode):
                                continue
                            expanded += st.st_size
                            count += 1
                            if count > MAX_ARCHIVE_FILES or expanded > MAX_ARCHIVE_BYTES:
                                raise ValueError('Backup exceeds archive entry or 512 MiB content limits')
                            archive.add(path, arcname=arc_dir + '/' + filename, recursive=False)
            if os.path.getsize(archive_path) > MAX_ARCHIVE_BYTES:
                raise ValueError('Compressed backup exceeds 512 MiB')
        except Exception:
            try:
                os.unlink(archive_path)
            except OSError:
                pass
            raise
        try:
            os.chmod(archive_path, 0o600)
        except OSError:
            pass
        return {'name': archive_name, 'path': archive_path, 'download_url': '/api/luanti/backup?name=' + archive_name,
                'entries': count, 'bytes': expanded, 'archive_bytes': os.path.getsize(archive_path)}

    def delete_item(self, category, name):
        if self.is_running():
            raise ValueError('Stop the Luanti server before deleting content')
        if category in ('userdata',):
            raise ValueError('Direct deletion of user-data items is disabled; create and verify a backup first')
        path = self._item_path(category, name)
        if category == 'worlds' and name == self.preferences.get('selected_world'):
            raise ValueError('Select a different world before deleting the configured server world')
        backup = self.backup_item(category, name)
        shutil.rmtree(path)
        return {'deleted': name, 'kind': category, 'backup': backup}

    def backup_path(self, name):
        if not valid_name(name) or not name.endswith('.tar.gz'):
            raise ValueError('Invalid Luanti backup name')
        path = os.path.join(self._backup_dir(), name)
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_ARCHIVE_BYTES:
            raise ValueError('Luanti backup file is invalid')
        return path

    def list_backups(self):
        if self.demo or not os.path.isdir(self._backup_dir()):
            return []
        result = []
        for name in sorted(os.listdir(self._backup_dir()), key=lambda item: item.lower(), reverse=True):
            if not valid_name(name) or not name.endswith('.tar.gz'):
                continue
            path = os.path.join(self._backup_dir(), name)
            try:
                st = os.lstat(path)
                if stat.S_ISREG(st.st_mode) and st.st_size <= MAX_ARCHIVE_BYTES:
                    result.append({'name': name, 'size': st.st_size, 'modified': int(st.st_mtime),
                                   'download_url': '/api/luanti/backup?name=' + name})
            except OSError:
                continue
        return result

    def log_tail(self, max_bytes=32768):
        if self.demo:
            return 'Demo mode: live Luanti logs are not read.'
        try:
            with open(self._log_path(), 'rb') as source:
                source.seek(0, os.SEEK_END)
                size = source.tell()
                source.seek(max(0, size - max_bytes))
                return source.read(max_bytes).decode('utf-8', 'replace')
        except OSError:
            return ''

    def _proc_start_ticks(self, pid):
        try:
            text = open('/proc/%d/stat' % pid, 'r').read()
            after = text[text.rfind(')') + 2:].split()
            return int(after[19])
        except Exception:
            return None

    def _load_pid(self):
        try:
            with open(self._pid_path(), 'r', encoding='utf-8') as source:
                value = json.load(source)
            if not isinstance(value, dict):
                return None
            pid = int(value.get('pid', 0))
            if pid <= 1 or pid == os.getpid():
                return None
            return value
        except Exception:
            return None

    def _matches_process(self, record):
        pid = int(record.get('pid', 0))
        expected_ticks = record.get('start_ticks')
        if pid <= 1 or expected_ticks is None or self._proc_start_ticks(pid) != expected_ticks:
            return False
        try:
            with open('/proc/%d/cmdline' % pid, 'rb') as source:
                argv = source.read(16384).decode('utf-8', 'replace').split('\x00')
            argv = [item for item in argv if item]
            binary = os.path.realpath(record.get('binary', ''))
            return bool(argv and os.path.realpath(argv[0]) == binary and
                        record.get('config_path') in argv and record.get('world_path') in argv)
        except Exception:
            return False

    def _process_record(self):
        record = self._load_pid()
        if record and self._matches_process(record):
            return record
        if record:
            try:
                os.unlink(self._pid_path())
            except OSError:
                pass
        return None

    def is_running(self):
        if self.demo:
            return False
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return True
            return self._process_record() is not None

    def status(self):
        if self.demo:
            return {'available': False, 'running': False, 'demo': True, 'binary_path': self.preferences['binary_path'],
                    'binary_available': False, 'selected_world': '', 'port': 30000, 'bind_address': '',
                    'log_path': '', 'paths': self._path_status(), 'note': 'Demo data only; the NAS and any Luanti server are not inspected.'}
        record = self._process_record()
        binary = self.preferences['binary_path']
        binary_available = os.path.isfile(binary) and not os.path.islink(binary) and os.access(binary, os.X_OK)
        worlds = {item['name'] for item in self.list_category('worlds')}
        selected = self.preferences.get('selected_world', '')
        config = self.read_config()
        run_as_user = self.preferences.get('run_as_user', '')
        try:
            self._account_entry(run_as_user)
            account_valid = True
        except ValueError:
            account_valid = False
        return {'available': binary_available, 'running': bool(record), 'demo': False,
                'binary_path': binary, 'binary_available': binary_available, 'pid': record.get('pid') if record else None,
                'selected_world': selected, 'world_exists': selected in worlds,
                'port': config['port'], 'bind_address': config['bind_address'],
                'run_as_user': run_as_user, 'account_valid': account_valid,
                'log_path': self._log_path(), 'paths': self._path_status(),
                'note': '' if binary_available else 'Luanti server executable was not found at the configured path.'}

    def _path_status(self):
        result = {}
        for key in ('binary_path', 'config_path', 'games_path', 'worlds_path', 'mods_path', 'skins_path', 'user_path'):
            path = self.preferences[key]
            result[key] = {'path': path, 'exists': os.path.exists(path),
                           'directory': os.path.isdir(path), 'writable': os.path.isdir(os.path.dirname(path) if key in ('binary_path', 'config_path') else path) and os.access(os.path.dirname(path) if key in ('binary_path', 'config_path') else path, os.W_OK)}
        return result

    def _auth_store(self):
        world_name = self.preferences.get('selected_world', '')
        if not world_name:
            return {'available': False, 'backend': '', 'path': '', 'note': 'Select a world first.'}
        world = self._item_path('worlds', world_name)
        world_settings = parse_conf(self._read_text(os.path.join(world, 'world.mt'), 1 << 20)) if os.path.exists(os.path.join(world, 'world.mt')) else {}
        configured = world_settings.get('auth_backend', '').lower()
        sqlite_path = os.path.join(world, 'auth.sqlite')
        files_path = os.path.join(world, 'auth.txt')
        if configured in ('sqlite3', 'sqlite'):
            backend, path = 'sqlite3', sqlite_path
        elif configured in ('files', 'file'):
            backend, path = 'files', files_path
        elif configured:
            return {'available': False, 'backend': configured, 'path': '', 'note': 'This authentication backend is not supported for offline management.'}
        elif os.path.isfile(sqlite_path):
            backend, path = 'sqlite3', sqlite_path
        elif os.path.isfile(files_path):
            backend, path = 'files', files_path
        else:
            return {'available': False, 'backend': '', 'path': '', 'note': 'The world has no authentication database yet; start it once, then stop it before managing players.'}
        if os.path.islink(path):
            raise ValueError('Luanti authentication database may not be a symlink')
        if os.path.exists(path):
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_ARCHIVE_BYTES:
                raise ValueError('Authentication database is not a permitted regular file')
        return {'available': os.path.isfile(path), 'backend': backend, 'path': path,
                'note': '' if os.path.isfile(path) else 'Authentication database will be created by Luanti when the world starts.'}

    def player_list(self):
        store = self._auth_store()
        if not store['available']:
            return dict(store, players=[])
        if store['backend'] == 'files':
            players = []
            with open(store['path'], 'r', encoding='utf-8', errors='replace') as source:
                for line in source:
                    row = line.rstrip('\r\n').split(':')
                    if not row or not PLAYER_RE.match(row[0]):
                        continue
                    privileges = [item for item in row[2].split(',') if item] if len(row) > 2 else []
                    players.append({'name': row[0], 'password_set': bool(row[1]) if len(row) > 1 else False,
                                    'last_login': None, 'privileges': privileges, 'online': None})
            players.sort(key=lambda item: item['name'].lower())
            return dict(store, players=players)
        try:
            import sqlite3
        except ImportError:
            return {'available': False, 'backend': store['backend'], 'path': store['path'], 'players': [],
                    'note': 'The installed Python runtime has no sqlite3 module; offline SQLite auth management is unavailable.'}
        from urllib.parse import quote
        uri = 'file:' + quote(os.path.abspath(store['path']), safe='/') + '?mode=ro'
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=2)
            connection.execute('PRAGMA query_only=ON')
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'auth' not in tables:
                raise ValueError('Authentication database has no expected auth table')
            columns = {row[1] for row in connection.execute('PRAGMA table_info(auth)')}
            if not {'name', 'password'}.issubset(columns):
                raise ValueError('Authentication table has an unsupported schema')
            if 'last_login' not in columns:
                last_expr = 'NULL'
            else:
                last_expr = 'last_login'
            rows = connection.execute('SELECT id, name, password, %s FROM auth ORDER BY name' % last_expr).fetchall() if 'id' in columns else connection.execute('SELECT NULL, name, password, %s FROM auth ORDER BY name' % last_expr).fetchall()
            has_privileges = 'user_privileges' in tables
            privileges_by_id = {}
            if has_privileges and 'id' in columns:
                priv_columns = {row[1] for row in connection.execute('PRAGMA table_info(user_privileges)')}
                if {'id', 'privilege'}.issubset(priv_columns):
                    for player_id, privilege in connection.execute('SELECT id, privilege FROM user_privileges ORDER BY privilege'):
                        privileges_by_id.setdefault(player_id, []).append(privilege)
            players = [{'name': name, 'password_set': bool(password), 'last_login': last_login,
                        'privileges': privileges_by_id.get(player_id, []), 'online': None}
                       for player_id, name, password, last_login in rows if isinstance(name, str) and PLAYER_RE.match(name)]
            connection.close()
            return dict(store, players=players)
        except sqlite3.DatabaseError as exc:
            try:
                connection.close()
            except Exception:
                pass
            raise ValueError('Cannot read Luanti auth database: ' + str(exc)[:250])

    def _check_player_name(self, name):
        if not isinstance(name, str) or not PLAYER_RE.match(name):
            raise ValueError('Player name must be 1–20 ASCII letters, digits, underscore or hyphen')
        return name

    def player_add(self, name):
        if self.is_running():
            raise ValueError('Stop the Luanti server before adding a player')
        name = self._check_player_name(name)
        store = self._auth_store()
        if not store['available']:
            raise ValueError(store['note'] or 'Authentication database is unavailable')
        if store['backend'] == 'files':
            with open(store['path'], 'r', encoding='utf-8', errors='replace') as source:
                lines = source.read().splitlines()
            if any(line.split(':', 1)[0] == name for line in lines):
                raise FileExistsError('Player already exists')
            self.backup_item('worlds', self.preferences['selected_world'])
            lines.append(name + '::')
            self._write_world_file(store['path'], ('\n'.join(lines).rstrip() + '\n').encode('utf-8'))
        else:
            try:
                import sqlite3
            except ImportError:
                raise RuntimeError('The installed Python runtime has no sqlite3 module')
            from urllib.parse import quote
            uri = 'file:' + quote(os.path.abspath(store['path']), safe='/') + '?mode=rw'
            connection = sqlite3.connect(uri, uri=True, timeout=5)
            try:
                connection.execute('PRAGMA foreign_keys=ON')
                columns = {row[1] for row in connection.execute('PRAGMA table_info(auth)')}
                if not {'name', 'password'}.issubset(columns):
                    raise ValueError('Authentication table has an unsupported schema')
                if connection.execute('SELECT 1 FROM auth WHERE name=?', (name,)).fetchone():
                    raise FileExistsError('Player already exists')
                self.backup_item('worlds', self.preferences['selected_world'])
                fields = ['name', 'password']
                values = [name, '']
                if 'last_login' in columns:
                    fields.append('last_login')
                    values.append(0)
                sql = 'INSERT INTO auth (%s) VALUES (%s)' % (','.join(fields), ','.join('?' for _ in fields))
                connection.execute('BEGIN IMMEDIATE')
                connection.execute(sql, values)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            self._set_auth_owner(store['path'])
        return {'name': name, 'password_set': False, 'note': 'Created without a password. Set one with Luanti before exposing the server to players.'}

    def player_delete(self, name):
        if self.is_running():
            raise ValueError('Stop the Luanti server before deleting a player')
        name = self._check_player_name(name)
        store = self._auth_store()
        if not store['available']:
            raise ValueError(store['note'] or 'Authentication database is unavailable')
        self.backup_item('worlds', self.preferences['selected_world'])
        if store['backend'] == 'files':
            with open(store['path'], 'r', encoding='utf-8', errors='replace') as source:
                lines = source.read().splitlines()
            kept = [line for line in lines if line.split(':', 1)[0] != name]
            if len(kept) == len(lines):
                raise FileNotFoundError('Player record was not found')
            self._write_world_file(store['path'], ('\n'.join(kept).rstrip() + ('\n' if kept else '')).encode('utf-8'))
        else:
            try:
                import sqlite3
            except ImportError:
                raise RuntimeError('The installed Python runtime has no sqlite3 module')
            from urllib.parse import quote
            uri = 'file:' + quote(os.path.abspath(store['path']), safe='/') + '?mode=rw'
            connection = sqlite3.connect(uri, uri=True, timeout=5)
            try:
                columns = {row[1] for row in connection.execute('PRAGMA table_info(auth)')}
                if not {'id', 'name'}.issubset(columns):
                    raise ValueError('Authentication table has an unsupported deletion schema')
                row = connection.execute('SELECT id FROM auth WHERE name=?', (name,)).fetchone()
                if not row:
                    raise FileNotFoundError('Player record was not found')
                connection.execute('BEGIN IMMEDIATE')
                if 'user_privileges' in {item[0] for item in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                    connection.execute('DELETE FROM user_privileges WHERE id=?', (row[0],))
                connection.execute('DELETE FROM auth WHERE id=?', (row[0],))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            self._set_auth_owner(store['path'])
        return {'name': name, 'deleted': True,
                'note': 'Authentication and privilege records were removed. Player inventory/position data remains in the world for recovery.'}

    def _write_world_file(self, path, data):
        if os.path.islink(path):
            raise ValueError('Luanti world metadata may not be a symlink')
        _write_atomic(path, data, 0o600)
        self._set_auth_owner(path)

    def _set_auth_owner(self, path):
        run_as = self.preferences.get('run_as_user', '')
        if run_as:
            entry, _groups = self._account_entry(run_as)
            os.chown(path, entry.pw_uid, entry.pw_gid)
            os.chmod(path, 0o600)

    def start(self, fixed_environment):
        if self.demo:
            raise ValueError('Demo mode does not start Luanti')
        with self.lock:
            if self.is_running():
                raise ValueError('Luanti server is already running')
            entry, groups = self._account_entry(self.preferences.get('run_as_user', ''))
            binary = self.validate_path(self.preferences['binary_path'], allow_missing=False)
            st = os.lstat(binary)
            if not stat.S_ISREG(st.st_mode) or not os.access(binary, os.X_OK):
                raise ValueError('Configured Luanti binary is not an executable regular file')
            self._account_access(binary, entry, groups, os.X_OK)
            world_name = self.preferences.get('selected_world', '')
            if not world_name:
                raise ValueError('Select a world before starting the server')
            world_path = self._item_path('worlds', world_name)
            game_id = self.world_game_id(world_name)
            if not game_id:
                raise ValueError('Selected world has no valid gameid in world.mt')
            self._item_path('games', game_id)
            config_path = self.validate_path(self.preferences['config_path'], allow_missing=True)
            if not os.path.exists(config_path):
                self.save_config('', self.preferences['port'], self.preferences['bind_address'])
            user_path = self.validate_path(self.preferences['user_path'], allow_missing=True)
            if not os.path.exists(user_path):
                parent = os.path.dirname(user_path)
                os.makedirs(parent, mode=0o755, exist_ok=True)
                if os.path.islink(parent):
                    raise ValueError('Luanti user-data parent may not be a symlink')
                os.mkdir(user_path, 0o700)
                os.chown(user_path, entry.pw_uid, entry.pw_gid)
            if not os.path.isdir(user_path):
                raise ValueError('Configured Luanti user-data path is not a directory')
            self._account_access(user_path, entry, groups, os.R_OK | os.W_OK | os.X_OK)
            games_path = self._category_root('games')
            mods_path = self._category_root('mods')
            os.makedirs(mods_path, mode=0o755, exist_ok=True)
            self._account_access(games_path, entry, groups, os.R_OK | os.X_OK)
            self._account_access(mods_path, entry, groups, os.R_OK | os.X_OK)
            self._account_access(world_path, entry, groups, os.R_OK | os.W_OK | os.X_OK)
            self._set_auth_owner(config_path)
            self._account_access(config_path, entry, groups, os.R_OK)
            log_path = self._log_path()
            os.makedirs(os.path.dirname(log_path), mode=0o700, exist_ok=True)
            env = dict(fixed_environment())
            env['LUANTI_GAME_PATH'] = games_path
            env['MINETEST_GAME_PATH'] = games_path
            env['LUANTI_MOD_PATH'] = mods_path
            env['MINETEST_MOD_PATH'] = mods_path
            env['LUANTI_USER_PATH'] = user_path
            env['MINETEST_USER_PATH'] = user_path
            env['HOME'] = user_path
            env['USER'] = entry.pw_name
            env['LOGNAME'] = entry.pw_name
            argv = [binary]
            if os.path.basename(binary).lower() in ('luanti', 'minetest'):
                argv.append('--server')
            argv.extend(['--config', config_path, '--world', world_path, '--port', str(self.preferences['port'])])
            log_file = open(log_path, 'ab', buffering=0)
            def drop_privileges():
                os.setgroups(sorted(groups))
                os.setgid(entry.pw_gid)
                os.setuid(entry.pw_uid)
            try:
                process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
                                           cwd=user_path, env=env, close_fds=True, start_new_session=True,
                                           preexec_fn=drop_privileges)
            finally:
                log_file.close()
            time.sleep(0.25)
            if process.poll() is not None:
                raise RuntimeError('Luanti exited during startup; inspect the server log')
            record = {'pid': process.pid, 'binary': os.path.realpath(binary), 'config_path': config_path,
                      'world_path': world_path, 'start_ticks': self._proc_start_ticks(process.pid),
                      'started_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')}
            _write_atomic(self._pid_path(), json.dumps(record, sort_keys=True).encode('utf-8'), 0o600)
            self.process = process
            return {'running': True, 'pid': process.pid, 'world': world_name, 'port': self.preferences['port'], 'log_path': log_path}

    def stop(self, timeout=12):
        if self.demo:
            raise ValueError('Demo mode does not stop Luanti')
        with self.lock:
            record = self._process_record()
            if not record:
                self.process = None
                return {'running': False, 'already_stopped': True}
            pid = int(record['pid'])
            proc = self.process if self.process is not None and self.process.pid == pid else None
            if not self._matches_process(record):
                raise ValueError('Luanti process identity changed; refusing to signal it')
            os.kill(pid, signal.SIGINT)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if proc is not None:
                    if proc.poll() is not None:
                        break
                elif not self._matches_process(record):
                    break
                time.sleep(0.2)
            if proc is not None and proc.poll() is None or proc is None and self._matches_process(record):
                if self._matches_process(record):
                    os.kill(pid, signal.SIGTERM)
                deadline = time.time() + 3
                while time.time() < deadline:
                    if proc is not None and proc.poll() is not None or proc is None and not self._matches_process(record):
                        break
                    time.sleep(0.2)
            if proc is not None and proc.poll() is None and self._matches_process(record):
                os.kill(pid, signal.SIGKILL)
                proc.wait(timeout=3)
            elif proc is None and self._matches_process(record):
                os.kill(pid, signal.SIGKILL)
            self.process = None
            try:
                os.unlink(self._pid_path())
            except OSError:
                pass
            return {'running': False, 'stopped': True, 'pid': pid}

    def restart(self, fixed_environment):
        self.stop()
        return self.start(fixed_environment)
