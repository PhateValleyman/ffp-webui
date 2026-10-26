# Luanti server management — sources and compatibility notes

## Server process and paths

- [Luanti server setup](https://docs.luanti.org/for-server-hosts/setup/) documents UDP server port 30000 as the recommended default, recommends leaving `bind_address` unset unless the host has multiple IP addresses, and says server setting changes take effect after restart. Public hosting also requires router/firewall UDP forwarding; the WebUI does not configure the router.
- [luanti(6) manual](https://man.archlinux.org/man/luantiserver.6.en) documents the `luantiserver` headless executable, `luanti --server`, and common options `--config`, `--world`, `--gameid`, and `--port`. `bind_address` is a configuration key, not a CLI flag.
- The same manual documents `LUANTI_GAME_PATH` and `LUANTI_MOD_PATH` as colon-delimited search paths and `LUANTI_USER_PATH` as a user-data path for non-run-in-place builds. The manager also sets legacy `MINETEST_*` aliases for older engine releases. An optional `skins_path` is an organizational/content path; the cited manual does not define a dedicated skin-path environment variable.
- [Luanti game directory API](https://api.luanti.org/games/) documents games under `$path_share/games/<gameid>/` or `$path_user/games/<gameid>/`; the directory may contain `game.conf`, `minetest.conf`, and `settingtypes.txt`.

## Authentication and player records

- [Luanti database backends](https://docs.luanti.org/for-server-hosts/database-backends/) says the world's `auth_backend` selects the authentication store, which contains credentials and privileges. SQLite3 is the usual/default backend; the legacy file backend is discouraged but still exists in old worlds.
- [Luanti world format (official source)](https://raw.githubusercontent.com/luanti-org/luanti/master/doc/world_format.md) documents per-world `auth.txt` and `auth.sqlite`. The SQLite schema has `auth(id, name, password, last_login)` and `user_privileges(id, privilege)` tables. A blank password field is a documented valid no-password entry in `auth.txt`; the WebUI therefore warns when it creates a player record and does not expose stored password hashes. Delete removes auth/privilege rows but deliberately leaves player position/inventory data for recovery.
- SQLite player changes require a stopped server, a pre-change world backup, parameterized SQL, and schema checks. If the NAS's static Python lacks the `sqlite3` module, SQLite player management reports unavailable rather than attempting a different database path.

## Security and target limitations

- This WebUI runs with root-level administrative capabilities and has no login. Luanti games/mods can execute code; only use trusted game and mod code. The manager permits an existing account including `root`, drops to the selected UID/GID and supplementary groups for the server process, and does not create or alter OS accounts. The selected account must be able to read games/mods/config and write the selected world and user-data directory.
- The repository's NAS profile targets a Zyxel NSA320 with FFP 0.7.0, Linux 2.6.31.8, ARMv5 soft-float, and static Python 3.13.16. The installed Luanti binary/version, SQLite auth schema on that device, and presence of an eligible non-root service account are not verified here. Build and host tests cannot substitute for a test start on that NAS.
