# GitHub release metadata for FFP-WebUI updater

## Verified public API response

Source: [GitHub Releases REST API — latest release](https://api.github.com/repos/PhateValleyman/ffp-webui/releases/latest)

The public endpoint was fetched on 2026-10-25 while the repository's latest release was `v0.9.5`. The response reported `draft: false` and `prerelease: false`. Its FFP installer asset was `ffp-webui-0.9.5-python3.13-static-UNVERIFIED.txz`, size 1,030,008 bytes, with GitHub asset digest `sha256:fcf0ac439071af0769a6d1cfd603163d4fa643ebfc618f02cee4cc1f9d27a59a`. GitHub also exposed the matching source archive, SHA-256 manifest and README as release assets.

This confirms that the public repository's release API currently returns an asset-level SHA-256 digest suitable for verifying a downloaded file before staging. The updater must refuse to stage a package when the digest is absent or invalid. A digest proves byte-for-byte integrity against the API response; it is not a signature and does not protect against a compromised repository account.

## Updater constraints

- Use only the fixed `PhateValleyman/ffp-webui` API endpoint over HTTPS and stable `vMAJOR.MINOR.PATCH` releases.
- Accept only the precisely named FFP-WebUI `.txz` asset, enforce a bounded size, and restrict redirects to GitHub release asset hosts.
- Do not access Zypkg, FFP catalogs, or general package repositories from the self-updater.
- Automatically download and stage a newer verified package; installation remains an explicit browser action. Keep the offline manual-transfer instructions available.

The target NAS's local firmware files were inspected: `command.js` maps package commands to `zy-pkgs` operations, and `broker.js` posts them to the same-origin privileged `../cgi-bin/zysh-cgi`. FFP-WebUI does not proxy that endpoint because its session/authentication and end-to-end response contract have not been validated from the separate UI origin; it links to the native firmware screens instead. No Zypkg install or uninstall command was invoked during testing.
