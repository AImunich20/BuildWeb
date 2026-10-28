#!/usr/bin/env node
// Set the app version everywhere it lives:  node scripts/set-version.js 0.1.7
// Prints the version that was set. With "next <latest>" it computes the next patch instead:
//   node scripts/set-version.js next 0.1.6   -> 0.1.7 (or package.json's version if that is higher)
const fs = require("fs");
const path = require("path");
const root = path.join(__dirname, "..");
const pkgPath = path.join(root, "package.json");
const cargoPath = path.join(root, "src-tauri", "Cargo.toml");

const parse = (v) => (v || "0.0.0").replace(/^v/, "").split(".").map((n) => parseInt(n, 10) || 0);
const cmp = (a, b) => { for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] - b[i]; return 0; };

const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
let version = process.argv[2];
if (version === "next") {
  const latest = parse(process.argv[3]);
  const current = parse(pkg.version);
  // A manual bump in package.json (e.g. 0.2.0) wins; otherwise continue after the latest release.
  version = cmp(current, latest) > 0 ? current.join(".") : [latest[0], latest[1], latest[2] + 1].join(".");
}
if (!/^\d+\.\d+\.\d+$/.test(version || "")) {
  console.error("usage: set-version.js <x.y.z> | next <latest>");
  process.exit(1);
}
pkg.version = version;
fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + "\n");
const cargo = fs.readFileSync(cargoPath, "utf8").replace(/^version = "[^"]*"/m, `version = "${version}"`);
fs.writeFileSync(cargoPath, cargo);
console.log(version);
