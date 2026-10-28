#!/bin/sh
# Copy the GrapesJS editor + plugins from node_modules into Django's static files (committed, so the
# backend runs without node).
set -e
cd "$(dirname "$0")/.."
NM=node_modules
OUT=backend/builder/static/vendor/grapesjs
rm -rf "$OUT" && mkdir -p "$OUT"
cp $NM/grapesjs/dist/grapes.min.js $NM/grapesjs/dist/css/grapes.min.css "$OUT/"
cp $NM/grapesjs-blocks-basic/dist/index.js "$OUT/blocks-basic.js"
cp $NM/grapesjs-plugin-forms/dist/index.js "$OUT/plugin-forms.js"
cp $NM/grapesjs-custom-code/dist/index.js "$OUT/custom-code.js"
cp $NM/grapesjs-navbar/dist/index.js "$OUT/navbar.js"
cp $NM/grapesjs-tabs/dist/grapesjs-tabs.min.js "$OUT/tabs.js"
cp $NM/grapesjs-component-countdown/dist/index.js "$OUT/countdown.js"
cp $NM/grapesjs-tooltip/dist/index.js "$OUT/tooltip.js"
cp $NM/grapesjs-parser-postcss/dist/index.js "$OUT/parser-postcss.js"
echo "Vendored GrapesJS $(node -p "require('./$NM/grapesjs/package.json').version") into $OUT"
