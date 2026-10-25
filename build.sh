#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DIST="$ROOT/dist"
STAGE="$DIST/stage"
VERSION=${VERSION:-0.9.5}

case "$VERSION" in
    ''|*[!0-9A-Za-z._-]*)
        echo "Invalid VERSION: $VERSION" >&2
        exit 2
        ;;
esac

PKG_NAME="ffp-webui-${VERSION}-python3.13-static-UNVERIFIED.txz"
SRC_NAME="ffp-webui-${VERSION}-source.tgz"
SUMS_NAME="ffp-webui-${VERSION}-SHA256SUMS"
PKG="$DIST/$PKG_NAME"
SRC="$DIST/$SRC_NAME"
SUMS="$DIST/$SUMS_NAME"

mkdir -p "$DIST"
rm -rf "$STAGE"
rm -f "$PKG" "$SRC" "$SUMS"

# Stage the Python executable, FFP startup/config files, and browser assets.
mkdir -p "$STAGE/ffp/bin" \
         "$STAGE/ffp/start" \
         "$STAGE/ffp/etc/ffp-webui" \
         "$STAGE/ffp/share/ffp-webui/assets"
cp "$ROOT/ffp/ffp/bin/ffp-webui" "$STAGE/ffp/bin/ffp-webui"
cp "$ROOT/ffp/ffp/bin/ffp_webui_rclone.py" "$STAGE/ffp/bin/ffp_webui_rclone.py"
cp "$ROOT/ffp/ffp/bin/ffp_webui_luanti.py" "$STAGE/ffp/bin/ffp_webui_luanti.py"
cp "$ROOT/ffp/ffp/start/ffp-webui.sh" "$STAGE/ffp/start/ffp-webui.sh"
cp "$ROOT/ffp/ffp/etc/ffp-webui/config.json" "$STAGE/ffp/etc/ffp-webui/config.json"
cp "$ROOT/internal/webui/assets/index.html" "$ROOT/internal/webui/assets/style.css" \
   "$ROOT/internal/webui/assets/app.js" "$ROOT/internal/webui/assets/icon.png" \
   "$STAGE/ffp/share/ffp-webui/assets/"

# Keep the server executable, startup hook executable, and config root-readable.
chmod 0755 "$STAGE/ffp/bin/ffp-webui" "$STAGE/ffp/start/ffp-webui.sh"
chmod 0644 "$STAGE/ffp/bin/ffp_webui_rclone.py" \
           "$STAGE/ffp/bin/ffp_webui_luanti.py" \
           "$STAGE/ffp/etc/ffp-webui/config.json" \
           "$STAGE/ffp/share/ffp-webui/assets/index.html" \
           "$STAGE/ffp/share/ffp-webui/assets/style.css" \
           "$STAGE/ffp/share/ffp-webui/assets/app.js" \
           "$STAGE/ffp/share/ffp-webui/assets/icon.png"

# Build a root-owned xz-compressed FFP .txz package for the target funpkg.
# UNVERIFIED stays in the filename until the bundle has been tested on the NAS.
cd "$STAGE"
tar --owner=0 --group=0 --numeric-owner -cJf "$PKG" ffp

# Create a clean source archive without private request notes, NAS probes, or caches.
cd "$ROOT"
tar --exclude='__pycache__' --exclude='*.pyc' -czf "$SRC" \
    README.md CHANGELOG.md build.sh go.mod cmd internal ffp tests \
    references/rclone-webui-integration-research.md \
    references/next-release-design-notes.md \
    references/luanti-management-sources.md

# Show artifact checksums, sizes, and staged entry points for review.
cd "$DIST"
sha256sum "$PKG_NAME" "$SRC_NAME" > "$SUMS_NAME"
cat "$SUMS_NAME"
ls -lh "$PKG_NAME" "$SRC_NAME" "$SUMS_NAME"
find "$STAGE/ffp" -type f -printf '%P %m %s bytes\n' | sort
