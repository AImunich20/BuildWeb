#!/usr/bin/env node
// After `tauri build`, gather this platform's installer + signed updater bundle into out/ and describe them
// in out/<platform>.json for the publish job.
//   node scripts/collect.js <platform> [rust-target]
// platform: darwin-aarch64 | darwin-x86_64 | windows-x86_64 | linux-x86_64
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const [platform, target] = process.argv.slice(2);
const root = path.join(__dirname, "..");
const version = require(path.join(root, "package.json")).version;
const bundle = path.join(root, "src-tauri", "target", ...(target ? [target] : []), "release", "bundle");
const out = path.join(root, "out");
fs.mkdirSync(out, { recursive: true });

const find = (dir, re) => {
  const d = path.join(bundle, dir);
  const hit = fs.existsSync(d) ? fs.readdirSync(d).find((f) => re.test(f)) : null;
  if (!hit) throw new Error(`no ${re} in ${d}`);
  return path.join(d, hit);
};
const copy = (src, name) => { fs.copyFileSync(src, path.join(out, name)); return name; };

const info = { platform, version, installers: [] };
if (platform.startsWith("darwin")) {
  const arch = platform.endsWith("aarch64") ? "aarch64" : "x64";
  // .dmg with hdiutil (Tauri's dmg step drives Finder via AppleScript, which is unreliable on CI).
  const stage = fs.mkdtempSync(path.join(require("os").tmpdir(), "dmg-"));
  execFileSync("cp", ["-R", path.join(bundle, "macos", "BuildWeb.app"), stage]);
  fs.symlinkSync("/Applications", path.join(stage, "Applications"));
  const dmg = `BuildWeb_${version}_${arch}.dmg`;
  execFileSync("hdiutil", ["create", "-volname", "BuildWeb", "-srcfolder", stage, "-ov", "-format", "UDZO", path.join(out, dmg)]);
  info.installers.push(dmg);
  info.file = copy(find("macos", /\.app\.tar\.gz$/), `BuildWeb_${version}_${arch}.app.tar.gz`);
  info.signature = fs.readFileSync(find("macos", /\.app\.tar\.gz\.sig$/), "utf8").trim();
} else if (platform.startsWith("windows")) {
  const exe = find("nsis", /-setup\.exe$/);
  info.file = copy(exe, `BuildWeb_${version}_x64-setup.exe`);
  info.installers.push(info.file);
  info.signature = fs.readFileSync(exe + ".sig", "utf8").trim();
} else {
  const appimage = find("appimage", /\.AppImage$/);
  info.file = copy(appimage, `BuildWeb_${version}_amd64.AppImage`);
  info.installers.push(info.file);
  info.signature = fs.readFileSync(appimage + ".sig", "utf8").trim();
  try { info.installers.push(copy(find("deb", /\.deb$/), `BuildWeb_${version}_amd64.deb`)); } catch (e) { console.warn(e.message); }
}
fs.writeFileSync(path.join(out, `${platform}.json`), JSON.stringify(info, null, 2));
console.log(JSON.stringify({ ...info, signature: info.signature.slice(0, 16) + "…" }, null, 2));
