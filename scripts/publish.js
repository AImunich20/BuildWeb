#!/usr/bin/env node
// Combine the per-platform outputs in dist/ into latest.json (Tauri updater feed) plus fixed-name download
// copies, then create the GitHub release.   node scripts/publish.js <repo> <version>   (needs GH_TOKEN, RELEASE_NOTES)
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const [repo, version] = process.argv.slice(2);
const dist = path.resolve("dist");
const infos = fs.readdirSync(dist).filter((f) => f.endsWith(".json") && f !== "latest.json")
  .map((f) => JSON.parse(fs.readFileSync(path.join(dist, f), "utf8")));
if (!infos.some((i) => i.platform === "darwin-aarch64")) throw new Error("the macOS (Apple silicon) build is missing; not publishing");
const missing = ["darwin-aarch64", "darwin-x86_64", "windows-x86_64", "linux-x86_64"].filter((p) => !infos.some((i) => i.platform === p));
if (missing.length) console.log(`::warning::publishing without: ${missing.join(", ")}`);

const url = (f) => `https://github.com/${repo}/releases/download/v${version}/${f}`;
const notes = process.env.RELEASE_NOTES || `BuildWeb v${version}`;
const latest = { version, notes, pub_date: new Date().toISOString(), platforms: {} };
for (const i of infos) latest.platforms[i.platform] = { signature: i.signature, url: url(i.file) };
fs.writeFileSync(path.join(dist, "latest.json"), JSON.stringify(latest, null, 2));

// Stable names for the download buttons: .../releases/latest/download/<name>
const fixed = {
  "darwin-aarch64": [[/\.dmg$/, "BuildWeb.dmg"]],
  "darwin-x86_64": [[/\.dmg$/, "BuildWeb-Intel.dmg"]],
  "windows-x86_64": [[/setup\.exe$/, "BuildWeb-Setup.exe"]],
  "linux-x86_64": [[/\.AppImage$/, "BuildWeb.AppImage"], [/\.deb$/, "BuildWeb.deb"]],
};
const files = new Set(["latest.json"]);
for (const i of infos) {
  files.add(i.file);
  i.installers.forEach((f) => files.add(f));
  for (const [re, name] of fixed[i.platform] || []) {
    const src = i.installers.find((f) => re.test(f));
    if (src) { fs.copyFileSync(path.join(dist, src), path.join(dist, name)); files.add(name); }
  }
}
const args = ["release", "create", `v${version}`, ...[...files].map((f) => path.join(dist, f)),
  "--repo", repo, "--title", `BuildWeb v${version}`, "--notes", notes];
console.log("gh", args.join(" "));
execFileSync("gh", args, { stdio: "inherit" });
console.log(`Published v${version}: ${infos.map((i) => i.platform).join(", ")}`);
