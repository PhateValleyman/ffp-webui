import os
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
        (self.paths['games_path'] / 'default').mkdir()
        self.manager = LuantiManager(
            state_root=str(self.root / 'state'),
            preferences_path=str(self.root / 'etc' / 'luanti.json'),
            find_binary=lambda _name: None,
        )
        self.manager.update_paths({key: str(value) for key, value in self.paths.items()})
        self.manager.create_world('main', 'default')

    def tearDown(self):
        self.temp.cleanup()

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

    def test_readme_is_plain_text_and_accepts_legacy_typo_filename(self):
        game = self.paths['games_path'] / 'default'
        (game / 'REDADME.md').write_text('# title\n<script>alert(1)</script>\n', encoding='utf-8')
        result = self.manager.read_readme('games', 'default')
        self.assertEqual(result['filename'], 'REDADME.md')
        self.assertIn('<script>', result['content'])

    def test_root_or_missing_accounts_are_not_accepted(self):
        with self.assertRaises(ValueError):
            self.manager._account_entry('root')
        with self.assertRaises(ValueError):
            self.manager._account_entry('user_that_does_not_exist_87233')

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
