import json
import os
import pwd
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / 'ffp' / 'ffp' / 'bin'
sys.path.insert(0, str(BIN_DIR))
from ffp_webui_luanti import LuantiManager  # noqa: E402


class LuantiManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = {
            'binary_path': self.root / 'bin' / 'luantiserver',
            'config_path': self.root / 'config' / 'minetest.conf',
            'games_path': self.root / 'games',
            'worlds_path': self.root / 'worlds',
            'mods_path': self.root / 'mods',
            'skins_path': self.root / 'skins',
            'user_path': self.root / 'userdata',
        }
        for path in self.paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        for key in ('games_path', 'worlds_path', 'mods_path', 'skins_path'):
            self.paths[key].mkdir(parents=True, exist_ok=True)
        default_game = self.paths['games_path'] / 'default'
        default_game.mkdir()
        (default_game / 'game.conf').write_text('title = Default Game\n', encoding='utf-8')
        self.manager = LuantiManager(
            state_root=str(self.root / 'state'),
            preferences_path=str(self.root / 'etc' / 'luanti.json'),
            find_binary=lambda _name: None,
        )
        self.manager.update_paths({key: str(value) for key, value in self.paths.items()})
        self.manager.create_world('main', 'default')

    def tearDown(self):
        self.temp.cleanup()

    def test_defaults_match_nas_screenshot_paths(self):
        manager = LuantiManager(
            state_root=str(self.root / 'defaults-state'),
            preferences_path=str(self.root / 'defaults.json'),
            find_binary=None,
        )
        expected = {
            'binary_path': '/ffp/bin/luantiserver',
            'config_path': '/ffp/etc/luanti/minetest.conf',
            'games_path': '/ffp/home/root/.minetest/games',
            'worlds_path': '/ffp/home/root/.minetest/worlds',
            'mods_path': '/ffp/home/root/.minetest/mods',
            'skins_path': '/ffp/home/root/.minetest/skins',
            'user_path': '/ffp/home/root/.minetest',
        }
        self.assertEqual({key: manager.preferences[key] for key in expected}, expected)

    def test_legacy_auto_defaults_migrate_but_path_only_values_persist(self):
        preferences = self.root / 'legacy-preferences.json'
        preferences.write_text(json.dumps({
            'binary_path': '/ffp/bin/minetestserver',
            'config_path': '/ffp/etc/minetest.conf',
            'games_path': '/ffp/share/luanti/games',
            'worlds_path': '/ffp/var/luanti/worlds',
            'mods_path': '/ffp/share/luanti/mods',
            'skins_path': '/ffp/share/luanti/skins',
            'user_path': '/ffp/var/luanti/user',
        }), encoding='utf-8')
        manager = LuantiManager(
            state_root=str(self.root / 'migrated-state'),
            preferences_path=str(preferences),
            find_binary=None,
        )
        expected = {
            'binary_path': '/ffp/bin/luantiserver',
            'config_path': '/ffp/etc/luanti/minetest.conf',
            'games_path': '/ffp/home/root/.minetest/games',
            'worlds_path': '/ffp/home/root/.minetest/worlds',
            'mods_path': '/ffp/home/root/.minetest/mods',
            'skins_path': '/ffp/home/root/.minetest/skins',
            'user_path': '/ffp/home/root/.minetest',
        }
        self.assertEqual({key: manager.preferences[key] for key in expected}, expected)
        self.assertEqual(manager.preferences['selected_world'], '')
        self.assertEqual(manager.preferences['run_as_user'], '')

    def test_previous_data_subdirectory_default_migrates_to_minetest_root(self):
        preferences = self.root / 'previous-defaults.json'
        preferences.write_text(json.dumps({
            'path_defaults_version': 2,
            'binary_path': '/ffp/bin/luantiserver',
            'config_path': '/ffp/etc/luanti/minetest.conf',
            'games_path': '/ffp/home/root/.minetest/games',
            'worlds_path': '/ffp/home/root/.minetest/worlds',
            'mods_path': '/ffp/home/root/.minetest/mods',
            'skins_path': '/ffp/home/root/.minetest/skins',
            'user_path': '/ffp/home/root/.minetest/data',
        }), encoding='utf-8')
        manager = LuantiManager(
            state_root=str(self.root / 'previous-defaults-state'),
            preferences_path=str(preferences),
            find_binary=None,
        )
        self.assertEqual(manager.preferences['user_path'], '/ffp/home/root/.minetest')
        self.assertEqual(manager.preferences['path_defaults_version'], 3)

    def test_paths_can_be_saved_without_world_or_service_account(self):
        preferences = self.root / 'path-only' / 'luanti.json'
        manager = LuantiManager(
            state_root=str(self.root / 'path-only-state'),
            preferences_path=str(preferences),
            find_binary=None,
        )
        values = {key: str(value) for key, value in self.paths.items()}
        with mock.patch.object(manager, '_account_entry', side_effect=AssertionError('path save must not inspect an account')):
            result = manager.update_paths_only(values)
        self.assertEqual(result['selected_world'], '')
        self.assertEqual(result['run_as_user'], '')
        self.assertEqual({key: result[key] for key in values}, values)
        reloaded = LuantiManager(
            state_root=str(self.root / 'path-only-state'),
            preferences_path=str(preferences),
            find_binary=None,
        )
        self.assertEqual({key: reloaded.preferences[key] for key in values}, values)
        self.assertEqual(reloaded.preferences['selected_world'], '')
        self.assertEqual(reloaded.preferences['run_as_user'], '')

    def test_minetest_user_root_can_contain_immediate_category_directories(self):
        user_root = self.root / '.minetest'
        user_root.mkdir()
        values = {
            'games_path': str(user_root / 'games'),
            'worlds_path': str(user_root / 'worlds'),
            'mods_path': str(user_root / 'mods'),
            'skins_path': str(user_root / 'skins'),
            'user_path': str(user_root),
        }
        for field in ('games_path', 'worlds_path', 'mods_path', 'skins_path'):
            Path(values[field]).mkdir()
        result = self.manager.update_paths_only(values)
        self.assertEqual({key: result[key] for key in values}, values)
        self.assertEqual(Path(result['user_path']).name, '.minetest')

    def test_minetest_user_root_exception_rejects_nested_category_path(self):
        user_root = self.root / '.minetest'
        values = {
            'games_path': str(user_root / 'games'),
            'worlds_path': str(user_root / 'worlds' / 'nested'),
            'mods_path': str(user_root / 'mods'),
            'skins_path': str(user_root / 'skins'),
            'user_path': str(user_root),
        }
        with self.assertRaisesRegex(ValueError, 'data paths may not overlap'):
            self.manager.update_paths_only(values)

    def test_minetest_user_root_exception_rejects_symlinked_category_alias(self):
        user_root = self.root / '.minetest'
        user_root.mkdir()
        (user_root / 'games').mkdir()
        (user_root / 'mods').symlink_to(user_root / 'games', target_is_directory=True)
        values = {
            'games_path': str(user_root / 'games'),
            'worlds_path': str(user_root / 'worlds'),
            'mods_path': str(user_root / 'mods'),
            'skins_path': str(user_root / 'skins'),
            'user_path': str(user_root),
        }
        with self.assertRaisesRegex(ValueError, 'data paths may not overlap'):
            self.manager.update_paths_only(values)

    def test_unrelated_user_root_cannot_contain_category_directories(self):
        user_root = self.root / 'minetest-data'
        values = {
            'games_path': str(user_root / 'games'),
            'worlds_path': str(user_root / 'worlds'),
            'mods_path': str(user_root / 'mods'),
            'skins_path': str(user_root / 'skins'),
            'user_path': str(user_root),
        }
        with self.assertRaisesRegex(ValueError, 'data paths may not overlap'):
            self.manager.update_paths_only(values)

    def test_failed_path_save_keeps_memory_and_disk_preferences_unchanged(self):
        old_preferences = dict(self.manager.preferences)
        preferences_file = Path(self.manager.preferences_path)
        old_file = preferences_file.read_bytes()
        replacement = str(self.root / 'replacement' / 'luantiserver')
        with mock.patch('ffp_webui_luanti._write_atomic', side_effect=OSError(30, 'Read-only file system')):
            with self.assertRaisesRegex(OSError, 'Read-only file system'):
                self.manager.update_paths_only({'binary_path': replacement})
        self.assertEqual(self.manager.preferences, old_preferences)
        self.assertEqual(preferences_file.read_bytes(), old_file)

    def test_path_default_migration_preserves_custom_directory(self):
        preferences = self.root / 'custom-preferences.json'
        custom_games = str(self.paths['games_path'])
        preferences.write_text(json.dumps({
            'games_path': custom_games,
            'worlds_path': '/ffp/var/luanti/worlds',
            'mods_path': '/ffp/share/luanti/mods',
            'skins_path': '/ffp/share/luanti/skins',
            'user_path': '/ffp/var/luanti/user',
        }), encoding='utf-8')
        manager = LuantiManager(
            state_root=str(self.root / 'custom-state'),
            preferences_path=str(preferences),
            find_binary=None,
        )
        self.assertEqual(manager.preferences['games_path'], custom_games)
        self.assertEqual(manager.preferences['worlds_path'], '/ffp/home/root/.minetest/worlds')
        self.assertEqual(manager.preferences['user_path'], '/ffp/var/luanti/user')

    def test_symlinked_home_paths_are_allowed_but_internal_state_aliases_are_not(self):
        home_target = self.root / 'home-target'
        home_target.mkdir()
        home_alias = self.root / 'home-alias'
        home_alias.symlink_to(home_target, target_is_directory=True)
        games_path = str(home_alias / '.minetest' / 'games')
        self.manager.update_paths({'games_path': games_path})
        self.assertEqual(self.manager.preferences['games_path'], games_path)
        state_alias = self.root / 'state-alias'
        state_alias.symlink_to(self.manager.state_root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'internal state'):
            self.manager.validate_path(str(state_alias / 'luanti' / 'outside'))

    def test_create_world_never_overwrites_existing_world(self):
        world = self.paths['worlds_path'] / 'main'
        sentinel = world / 'preserve-me.txt'
        sentinel.write_text('existing world data', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            self.manager.create_world('main', 'default')
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'existing world data')

    def set_auth_file(self, rows=''):
        world = self.paths['worlds_path'] / 'main'
        self.manager._write_world_file(world / 'world.mt', b'gameid = default\nauth_backend = files\n')
        self.manager._write_world_file(world / 'auth.txt', rows.encode('utf-8'))

    def set_auth_sqlite(self):
        world = self.paths['worlds_path'] / 'main'
        self.manager._write_world_file(world / 'world.mt', b'gameid = default\nauth_backend = sqlite3\n')
        db = sqlite3.connect(world / 'auth.sqlite')
        db.execute('CREATE TABLE auth (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(32) UNIQUE, password VARCHAR(512), last_login INTEGER)')
        db.execute('CREATE TABLE user_privileges (id INTEGER, privilege VARCHAR(32), PRIMARY KEY (id, privilege))')
        db.execute('INSERT INTO auth(name, password, last_login) VALUES (?, ?, ?)', ('alice', '#1#not-returned', 1234))
        db.execute('INSERT INTO user_privileges(id, privilege) VALUES (1, ?)', ('interact',))
        db.commit()
        db.close()

    def test_files_auth_add_and_delete_preserve_other_records(self):
        self.set_auth_file('alice:hash:interact,shout\n')
        result = self.manager.player_add('bob')
        self.assertFalse(result['password_set'])
        players = self.manager.player_list()
        self.assertEqual([player['name'] for player in players['players']], ['alice', 'bob'])
        self.assertTrue(next(player for player in players['players'] if player['name'] == 'alice')['password_set'])
        deleted = self.manager.player_delete('alice')
        self.assertTrue(deleted['deleted'])
        remaining = self.manager.player_list()['players']
        self.assertEqual([player['name'] for player in remaining], ['bob'])
        auth_text = (self.paths['worlds_path'] / 'main' / 'auth.txt').read_text()
        self.assertNotIn('alice:', auth_text)
        self.assertTrue(self.manager.list_backups())

    def test_sqlite_auth_add_and_delete_never_exposes_password_hash(self):
        self.set_auth_sqlite()
        listed = self.manager.player_list()
        self.assertEqual(listed['backend'], 'sqlite3')
        self.assertEqual(listed['players'][0]['name'], 'alice')
        self.assertEqual(listed['players'][0]['privileges'], ['interact'])
        self.assertNotIn('password', listed['players'][0])
        self.assertTrue(listed['players'][0]['password_set'])
        self.manager.player_add('bob')
        self.manager.player_delete('bob')
        db = sqlite3.connect(self.paths['worlds_path'] / 'main' / 'auth.sqlite')
        self.assertEqual(db.execute('SELECT name FROM auth ORDER BY name').fetchall(), [('alice',)])
        self.assertEqual(db.execute('SELECT privilege FROM user_privileges WHERE id=1').fetchall(), [('interact',)])
        db.close()
        self.assertGreaterEqual(len(self.manager.list_backups()), 2)

    def test_player_changes_require_server_stopped_and_valid_name(self):
        self.set_auth_file('')
        with mock.patch.object(self.manager, 'is_running', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Stop the Luanti server'):
                self.manager.player_add('player1')
        with self.assertRaisesRegex(ValueError, 'Player name'):
            self.manager.player_add('../bad')

    def test_config_refuses_disabling_mod_security(self):
        with self.assertRaisesRegex(ValueError, 'mod security may not be disabled'):
            self.manager.save_config('secure.enable_security = false\n', 30000, '')
        self.manager.save_config('secure.enable_security = true\n', 30000, '')
        saved = self.manager.read_config()
        self.assertIn('secure.enable_security = true', saved['content'])

    def test_import_rejects_path_traversal_and_leaves_no_target(self):
        archive = self.root / 'unsafe.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            payload = self.root / 'payload'
            payload.write_text('bad')
            tar.add(payload, arcname='../escaped')
        with self.assertRaisesRegex(ValueError, 'unsafe path'):
            self.manager.import_archive('mods', 'evil', str(archive))
        self.assertFalse((self.paths['mods_path'] / 'evil').exists())
        self.assertFalse((self.root / 'escaped').exists())

    def test_import_never_overwrites_an_existing_world(self):
        archive = self.root / 'world-import.tar.gz'
        payload = self.root / 'incoming-world'
        payload.mkdir()
        (payload / 'world.mt').write_text('gameid = default\n', encoding='utf-8')
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(payload, arcname='main')
        sentinel = self.paths['worlds_path'] / 'main' / 'preserve-me.txt'
        sentinel.write_text('existing world data', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            self.manager.import_archive('worlds', 'main', str(archive))
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'existing world data')

    def test_readme_is_plain_text_and_accepts_legacy_typo_filename(self):
        game = self.paths['games_path'] / 'default'
        (game / 'REDADME.md').write_text('# title\n<script>alert(1)</script>\n', encoding='utf-8')
        result = self.manager.read_readme('games', 'default')
        self.assertEqual(result['filename'], 'REDADME.md')
        self.assertIn('<script>', result['content'])

    def test_root_is_an_available_and_valid_service_account(self):
        entry, groups = self.manager._account_entry('root')
        self.assertEqual(entry.pw_uid, 0)
        self.assertIn(entry.pw_gid, groups)
        self.assertIn('root', [account['name'] for account in self.manager.run_as_users()])
        inaccessible = self.root / 'root-readable-only'
        inaccessible.write_text('content')
        inaccessible.chmod(0)
        self.manager._account_access(str(inaccessible), entry, groups, os.R_OK | os.W_OK)
        with self.assertRaises(ValueError):
            self.manager._account_entry('user_that_does_not_exist_87233')

    def test_list_mods_reads_enabled_state_from_selected_world(self):
        mod_path = self.paths['mods_path'] / 'example'
        mod_path.mkdir()
        (mod_path / 'mod.conf').write_text('name = Example Mod\n', encoding='utf-8')
        world_mt = self.paths['worlds_path'] / 'main' / 'world.mt'

        listed = self.manager.list_category('mods')
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['title'], 'Example Mod')
        self.assertFalse(listed[0]['enabled'])

        world_mt.write_text('gameid = default\nload_mod_example = true\n', encoding='utf-8')
        self.assertTrue(self.manager.list_category('mods')[0]['enabled'])
        world_mt.write_text('gameid = default\nload_mod_example = false\n', encoding='utf-8')
        self.assertFalse(self.manager.list_category('mods')[0]['enabled'])
        world_mt.write_text('gameid = default\nload_mod_example = mods/example\n', encoding='utf-8')
        self.assertTrue(self.manager.list_category('mods')[0]['enabled'])

    def test_mod_enabled_is_unknown_without_selected_world(self):
        mod_path = self.paths['mods_path'] / 'example'
        mod_path.mkdir()
        self.manager.update_paths({'selected_world': ''})
        self.assertIsNone(self.manager.mod_enabled('example'))
        self.assertIsNone(self.manager.list_category('mods')[0]['enabled'])

    def test_list_mods_reads_selected_world_configuration_once(self):
        for name in ('example', 'another'):
            mod_path = self.paths['mods_path'] / name
            mod_path.mkdir()
            (mod_path / 'mod.conf').write_text('name = %s\n' % name, encoding='utf-8')
        (self.paths['worlds_path'] / 'main' / 'world.mt').write_text(
            'gameid = default\nload_mod_example = true\n', encoding='utf-8')
        with mock.patch.object(self.manager, '_world_conf', wraps=self.manager._world_conf) as world_conf:
            listed = self.manager.list_category('mods')
        self.assertEqual(world_conf.call_count, 1)
        enabled = {item['name']: item['enabled'] for item in listed}
        self.assertTrue(enabled['example'])
        self.assertFalse(enabled['another'])

    def test_reported_nas_layout_uses_minetest_game_folder_for_minetest_id(self):
        default_game = self.paths['games_path'] / 'default'
        (default_game / 'game.conf').unlink()
        default_game.rmdir()
        for folder, title in (('devtest', 'Development Test'), ('minetest_game', 'Minetest Game')):
            game_path = self.paths['games_path'] / folder
            game_path.mkdir()
            (game_path / 'game.conf').write_text('title = %s\n' % title, encoding='utf-8')

        for name, game_id in (('p', 'minetest'), ('server', 'minetest'), ('t', 'extra_ordinance'),
                              ('world', 'minetest'), ('worldmods', '')):
            world_path = self.paths['worlds_path'] / name
            world_path.mkdir()
            text = 'world_name = %s\n' % name
            if game_id:
                text += 'gameid = %s\n' % game_id
            (world_path / 'world.mt').write_text(text, encoding='utf-8')

        games = {item['name']: item.get('gameid') for item in self.manager.list_category('games')}
        self.assertEqual(games['devtest'], 'devtest')
        self.assertEqual(games['minetest_game'], 'minetest')
        worlds = {item['name']: item for item in self.manager.list_category('worlds')}
        for name in ('p', 'server', 'world'):
            self.assertEqual(worlds[name]['gameid'], 'minetest')
            self.assertEqual(worlds[name]['resolved_gameid'], 'minetest')
        self.assertEqual(worlds['t']['gameid'], 'extra_ordinance')
        self.assertEqual(worlds['t']['resolved_gameid'], '')
        self.assertEqual(worlds['worldmods']['gameid'], '')
        self.assertEqual(worlds['worldmods']['resolved_gameid'], '')
        self.assertEqual(self.manager._resolve_game('minetest')['name'], 'minetest_game')
        with self.assertRaisesRegex(ValueError, 'not installed'):
            self.manager._resolve_game('extra_ordinance')

    def test_game_alias_and_id_field_handling_canonicalize_worlds(self):
        game_path = self.paths['games_path'] / 'renamed_game'
        game_path.mkdir()
        (game_path / 'game.conf').write_text(
            'title = Renamed Game\nid = ignored_custom_id\naliases = old_name, old_game\n',
            encoding='utf-8')
        games = {item['name']: item for item in self.manager.list_category('games')}
        self.assertEqual(games['renamed_game']['gameid'], 'renamed')
        self.assertEqual(games['renamed_game']['aliases'], ['old_name', 'old'])
        self.assertEqual(self.manager._resolve_game('old_name')['name'], 'renamed_game')
        created = self.manager.create_world('renamed-world', 'renamed_game')
        self.assertEqual(created['gameid'], 'renamed')
        changed = self.manager.set_world_game('main', 'old_name')
        self.assertEqual(changed['gameid'], 'renamed')
        self.assertEqual(self.manager.world_game_id('main'), 'renamed')

    def test_duplicate_normalized_game_ids_fail_closed(self):
        for folder in ('collision', 'collision_game'):
            game_path = self.paths['games_path'] / folder
            game_path.mkdir()
            (game_path / 'game.conf').write_text('title = Collision\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.manager._resolve_game('collision')

    def test_start_passes_root_identity_to_the_luanti_process(self):
        minetest_game = self.paths['games_path'] / 'minetest_game'
        minetest_game.mkdir()
        (minetest_game / 'game.conf').write_text('title = Minetest Game\n', encoding='utf-8')
        (self.paths['worlds_path'] / 'main' / 'world.mt').write_text('gameid = minetest\n', encoding='utf-8')
        binary = self.paths['binary_path']
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o755)
        self.manager.update_paths({'run_as_user': 'root', 'selected_world': 'main'})
        process = mock.Mock(pid=43210)
        process.poll.return_value = None
        with mock.patch('ffp_webui_luanti.os.chown'), \
             mock.patch('ffp_webui_luanti.subprocess.Popen', return_value=process) as popen, \
             mock.patch('ffp_webui_luanti.time.sleep'), \
             mock.patch.object(self.manager, '_proc_start_ticks', return_value=123):
            result = self.manager.start(lambda: {})
            with mock.patch('ffp_webui_luanti.os.setgroups') as setgroups, \
                 mock.patch('ffp_webui_luanti.os.setgid') as setgid, \
                 mock.patch('ffp_webui_luanti.os.setuid') as setuid:
                popen.call_args.kwargs['preexec_fn']()
        self.assertTrue(result['running'])
        self.assertEqual(result['world'], 'main')
        self.assertEqual(popen.call_args.args[0][popen.call_args.args[0].index('--world') + 1],
                         str(self.paths['worlds_path'] / 'main'))
        self.assertEqual(popen.call_args.kwargs['env']['LUANTI_USER_PATH'], str(self.paths['user_path']))
        self.assertEqual(popen.call_args.kwargs['cwd'], str(self.paths['user_path']))
        setgroups.assert_called_once_with([0])
        setgid.assert_called_once_with(0)
        setuid.assert_called_once_with(0)
        self.assertEqual(pwd.getpwnam('root').pw_uid, 0)

    def test_frontend_exposes_safe_luanti_and_player_controls(self):
        html = (ROOT / 'internal' / 'webui' / 'assets' / 'index.html').read_text(encoding='utf-8')
        js = (ROOT / 'internal' / 'webui' / 'assets' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('data-view="luanti"', html)
        self.assertIn('id="luanti-player-form"', html)
        self.assertIn('/api/luanti/players', js)
        self.assertIn('function renderLuantiMarkdown', js)
        self.assertNotIn('innerHTML', js[js.index('function renderLuantiMarkdown'):js.index("$('#luanti-readme-close')")])


if __name__ == '__main__':
    unittest.main()
