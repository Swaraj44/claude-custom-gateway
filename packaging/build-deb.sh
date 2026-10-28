#!/usr/bin/env bash
# Build claude-custom-gateway_<version>_<arch>.deb into ./dist
# Needs: dpkg-deb, python3 with pip (and network, to fetch dependency wheels).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERE="$ROOT/packaging"
VERSION="$(sed -n 's/^version *= *"\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
ARCH="$(dpkg --print-architecture)"
PYMM="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
NAME="claude-custom-gateway"
STAGE="$(mktemp -d)"
PKG="$STAGE/pkg"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$PKG/DEBIAN" "$PKG/opt/$NAME/wheels" "$PKG/usr/bin" \
         "$PKG/lib/systemd/system" "$PKG/etc/default" "$ROOT/dist"

# Wheels: the app itself plus every dependency (resolved for this Python/arch).
python3 -m pip wheel --quiet --no-cache-dir "$ROOT" -w "$PKG/opt/$NAME/wheels"

# Command wrappers (venv is created by postinst).
for cmd in claude-custom-gateway claude-pro claude-debug; do
    printf '#!/bin/sh\nexec /opt/%s/venv/bin/%s "$@"\n' "$NAME" "$cmd" > "$PKG/usr/bin/$cmd"
    chmod 755 "$PKG/usr/bin/$cmd"
done

install -m 644 "$HERE/$NAME@.service" "$PKG/lib/systemd/system/$NAME@.service"
install -m 644 "$HERE/debian/default" "$PKG/etc/default/$NAME"
echo "/etc/default/$NAME" > "$PKG/DEBIAN/conffiles"
install -m 755 "$HERE/debian/postinst" "$HERE/debian/prerm" "$HERE/debian/postrm" "$PKG/DEBIAN/"

find "$PKG" -type d -exec chmod 755 {} +
SIZE="$(du -sk "$PKG" | cut -f1)"
cat > "$PKG/DEBIAN/control" <<CTL
Package: $NAME
Version: $VERSION
Architecture: $ARCH
Maintainer: Swaraj <swaraj@mislbd.com>
Installed-Size: $SIZE
Depends: python3 (>= $PYMM), python3-venv, python3-pip
Section: web
Priority: optional
Description: Streaming REST gateway to the Claude Code CLI
 Web UI, native chat API and OpenAI-compatible API in front of the
 Claude Code CLI. Runs as a systemd service (claude-custom-gateway@USER).
 Requires the 'claude' CLI to be installed and logged in for that user.
CTL

OUT="$ROOT/dist/${NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$PKG" "$OUT"
echo "Built $OUT"
