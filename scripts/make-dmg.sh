#!/bin/sh
# Package the built .app into a .dmg with hdiutil (avoids Tauri's Finder AppleScript step,
# which times out in headless/remote sessions).
set -e
cd "$(dirname "$0")/.."
VERSION=$(node -p "require('./package.json').version")
BUNDLE=src-tauri/target/release/bundle
OUT="$BUNDLE/dmg/BuildWeb_${VERSION}_$(uname -m).dmg"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp -R "$BUNDLE/macos/BuildWeb.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
mkdir -p "$BUNDLE/dmg"
hdiutil create -volname BuildWeb -srcfolder "$STAGE" -ov -format UDZO "$OUT" >/dev/null
echo "Created $OUT"
# Keep a copy somewhere easy to find.
DEST=${BUILDWEB_DMG_DIR:-release}
mkdir -p "$DEST"
cp "$OUT" "$DEST/"
echo "Copied to $DEST/$(basename "$OUT")"
