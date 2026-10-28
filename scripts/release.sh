#!/bin/sh
# Build a signed release: .dmg + updater bundle (.app.tar.gz + .sig) + latest.json.
#   sh scripts/release.sh            build only, files in src-tauri/target/release/bundle/release/
#   sh scripts/release.sh --publish  also create GitHub release v<version> with those files
# Version comes from package.json. Notes: RELEASE_NOTES="..." sh scripts/release.sh --publish
set -e
cd "$(dirname "$0")/.."
VERSION=$(node -p "require('./package.json').version")
REPO=${BUILDWEB_REPO:-AImunich20/buildweb-releases}
# CI passes the key itself in TAURI_SIGNING_PRIVATE_KEY; locally it is read from ~/.tauri/buildweb.key.
if [ -z "$TAURI_SIGNING_PRIVATE_KEY" ]; then
  KEY=${TAURI_SIGNING_PRIVATE_KEY_PATH:-$HOME/.tauri/buildweb.key}
  [ -f "$KEY" ] || { echo "Signing key not found: $KEY"; exit 1; }
  export TAURI_SIGNING_PRIVATE_KEY="$(cat "$KEY")"
fi
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}"

npx tauri build --bundles app
sh scripts/make-dmg.sh

case "$(uname -m)" in arm64) ARCH=aarch64 ;; *) ARCH=x86_64 ;; esac
BUNDLE=src-tauri/target/release/bundle
OUT=$BUNDLE/release
rm -rf "$OUT" && mkdir -p "$OUT"
TAR="BuildWeb_${VERSION}_${ARCH}.app.tar.gz"
DMG="BuildWeb_${VERSION}_$(uname -m).dmg"
cp "$BUNDLE/macos/BuildWeb.app.tar.gz" "$OUT/$TAR"
cp "$BUNDLE/macos/BuildWeb.app.tar.gz.sig" "$OUT/$TAR.sig"
cp "$BUNDLE/dmg/$DMG" "$OUT/$DMG"
# Same file under a fixed name, so .../releases/latest/download/BuildWeb.dmg always works.
cp "$BUNDLE/dmg/$DMG" "$OUT/BuildWeb.dmg"

VERSION="$VERSION" ARCH="$ARCH" TAR="$TAR" REPO="$REPO" SIG="$(cat "$OUT/$TAR.sig")" NOTES="${RELEASE_NOTES:-BuildWeb v$VERSION}" \
  node -e '
    const e = process.env;
    const json = {
      version: e.VERSION,
      notes: e.NOTES,
      pub_date: new Date().toISOString(),
      platforms: { [`darwin-${e.ARCH}`]: { signature: e.SIG, url: `https://github.com/${e.REPO}/releases/download/v${e.VERSION}/${e.TAR}` } },
    };
    require("fs").writeFileSync(process.argv[1], JSON.stringify(json, null, 2));
  ' "$OUT/latest.json"
echo "Release files in $OUT:"
ls -1 "$OUT"

if [ "$1" = "--publish" ]; then
  gh release create "v$VERSION" "$OUT/$DMG" "$OUT/BuildWeb.dmg" "$OUT/$TAR" "$OUT/$TAR.sig" "$OUT/latest.json" \
    --repo "$REPO" --title "BuildWeb v$VERSION" --notes "${RELEASE_NOTES:-BuildWeb v$VERSION}"
fi
