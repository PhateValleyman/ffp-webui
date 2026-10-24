# Rclone integration: compatibility and API findings

## Target compatibility

The target owner reports an on-device test of `rclone v1.65.2-DEV`: Linux `2.6.31.8` on `armv5tel`, `os/arch=arm (ARMv5 compatible, no hardfloat)`, built with Go `1.19.3`, static linking. The command succeeded on the NAS. This is direct owner-provided evidence and supersedes the earlier assumption that no viable Go/rclone build could run there.

Current official rclone downloads are v1.75.2 and document Linux kernel 3.2 as the minimum. Its release directory includes generic `linux-arm`, `linux-arm-v6`, and `linux-arm-v7` assets, but no explicit `armv5`-named package. These newer artifacts are not candidates for the kernel 2.6.31.8 NAS; use the already installed, owner-tested rclone v1.65.2-DEV instead.

## UI and Remote Control API

Rclone’s official GUI includes Dashboard, Explorer, Remotes, Mounts, Serves, and Settings. Since v1.74 it is an embedded compressed frontend served by rclone; `rclone gui` launches separate GUI and RC servers. The FFP project should integrate selected workflows into its own interface, not embed the full GUI.

The RC API is an HTTP JSON API; requests use POST. Relevant endpoints include `config/listremotes` (remote names), `operations/list` (directory entries), `sync/copy` (non-deleting copy between source and destination filesystems), and `_async=true` followed by `job/status`/`job/list` for background jobs. `sync/sync` can delete destination-only files and should not be the default transfer action.

Rclone’s RC interface has broad authority (configuration and filesystem access, and command execution under the rclone process identity). Keep its listener bound to loopback (`127.0.0.1`); expose only explicit, validated FFP WebUI routes to the browser. Do not publish a general-purpose RC proxy.

## Sources

- Rclone GUI, features and serving model: https://rclone.org/gui/
- Rclone GUI command/flags: https://rclone.org/commands/rclone_gui/
- Rclone Remote Control API and security: https://rclone.org/rc/
- Current rclone OS requirements: https://rclone.org/downloads/
- v1.75.2 artifact list: https://downloads.rclone.org/v1.75.2/
- Go Linux/ARM kernel and GOARM information: https://go.dev/wiki/Linux
- Rclone v1.65.1 compatibility discussion: https://github.com/rclone/rclone/issues/7571

## Configuration wizard and storage connection (2026-10-25)

The rclone v1.65.2 RC interface documents `config/providers` for backend option metadata, `config/listremotes` for configured remotes, and `config/create` with `nonInteractive`, `continue`, `state`, and `result` options. A non-interactive create can return an `Option`, `State`, and `Error`; applications prompt for the returned option and resume with the saved state plus the answer. Password fields should be collected as secrets and must not be returned in provider defaults. The WebUI implementation uses the config-create protocol for a generic remote wizard. Provider-specific OAuth callback behavior has not been verified on the NAS; the wizard does not claim automated OAuth completion.

Sources: https://raw.githubusercontent.com/rclone/rclone/v1.65.2/docs/content/rc.md ; https://rclone.org/commands/rclone_config_create/ ; https://rclone.org/rc/.
