#!/usr/bin/env node
// Copy the Django backend + the uv binary into src-tauri/backend-stage/ (bundled into the app's resources).
// Cross-platform (macOS, Windows, Linux). UV_BIN overrides which uv binary is bundled (e.g. another arch).
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const root = path.join(__dirname, "..");
const stage = path.join(root, "src-tauri", "backend-stage");
const skip = new Set([".venv", ".data", "__pycache__", "tests.py", ".DS_Store"]);

fs.rmSync(stage, { recursive: true, force: true });
fs.mkdirSync(path.join(stage, "bin"), { recursive: true });
fs.cpSync(path.join(root, "backend"), path.join(stage, "backend"), {
  recursive: true,
  filter: (src) => !skip.has(path.basename(src)) && !src.endsWith(".pyc"),
});

const exe = process.platform === "win32" ? "uv.exe" : "uv";
let uv = process.env.UV_BIN;
if (!uv) {
  try {
    uv = execSync(process.platform === "win32" ? "where uv" : "command -v uv", { encoding: "utf8", shell: true })
      .split(/\r?\n/)[0].trim();
  } catch {
    uv = path.join(require("os").homedir(), ".local", "bin", exe);
  }
}
if (!fs.existsSync(uv)) {
  console.error(`uv not found (${uv}); install uv or set UV_BIN`);
  process.exit(1);
}
const dest = path.join(stage, "bin", exe);
fs.copyFileSync(uv, dest);
fs.chmodSync(dest, 0o755);
console.log(`Staged backend + ${uv}`);
