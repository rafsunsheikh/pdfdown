#!/usr/bin/env node
// npm launcher for the pdfdown Python package.
//
// pdfdown is written in Python and needs Python 3.11 to 3.14 (3.11 to 3.14 are tested; the
// npm package pins nothing). This script runs it:
//   0. missing pieces are installed first with the bundled installer (install.ps1 on Windows: the
//      Visual C++ Runtime and uv; install.sh elsewhere: uv), so nothing has to be set up by hand
//   1. uv     ->  uvx --python 3.12 --from pdfdown==<version> pdfdown ...
//                 (uv downloads Python 3.12 by itself when it is missing)
//   2. python ->  a private virtual environment in ~/.cache/pdfdown-npm/<version>,
//                 created once with pip from a Python 3.11 to 3.14 and reused after that.
//
// Environment variables:
//   PDFDOWN_PYTHON    python executable to use for option 2
//   PDFDOWN_PIP_SPEC  what to pip install instead of pdfdown==<version> (e.g. a local wheel)
//   PDFDOWN_LAUNCHER  force "uvx" or "venv"

"use strict";

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const VERSION = require("../package.json").version;
const SPEC = process.env.PDFDOWN_PIP_SPEC || `pdfdown==${VERSION}`;
const ARGS = process.argv.slice(2);
const IS_WIN = process.platform === "win32";

function has(cmd) {
  return spawnSync(cmd, ["--version"], { stdio: "ignore", shell: IS_WIN }).status === 0;
}

function run(cmd, args) {
  const result = spawnSync(cmd, args, { stdio: "inherit", shell: IS_WIN });
  if (result.error) {
    console.error(`pdfdown: could not start ${cmd}: ${result.error.message}`);
    process.exit(1);
  }
  process.exit(result.status === null ? 1 : result.status);
}

function findPython() {
  const candidates = process.env.PDFDOWN_PYTHON ? [process.env.PDFDOWN_PYTHON]
    : IS_WIN ? ["py -3.12", "py -3.13", "py -3.11", "python"]
    : ["python3.12", "python3.13", "python3.14", "python3.11", "python3", "python"];
  const test = "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) else 1)";
  for (const py of candidates) {
    const [cmd, ...pre] = py.split(" ");
    if (spawnSync(cmd, [...pre, "-c", test], { stdio: "ignore", shell: IS_WIN }).status === 0) return [cmd, pre];
  }
  return null;
}

function viaVenv() {
  const cacheRoot = process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache");
  const venv = path.join(cacheRoot, "pdfdown-npm", VERSION);
  const exe = IS_WIN ? path.join(venv, "Scripts", "pdfdown.exe") : path.join(venv, "bin", "pdfdown");
  if (!fs.existsSync(exe)) {
    const found = findPython();
    if (!found) {
      console.error("pdfdown needs Python 3.11 to 3.14. Install uv (https://docs.astral.sh/uv/), which fetches " +
                    "the right Python by itself, or Python 3.12 from https://www.python.org/downloads/, then run this again.");
      process.exit(1);
    }
    const [py, pre] = found;
    console.error(`pdfdown: first run, installing ${SPEC} into ${venv} (one time only, about 1 GB with PyTorch) ...`);
    fs.mkdirSync(path.dirname(venv), { recursive: true });
    for (const step of [
      [py, [...pre, "-m", "venv", venv]],
      [IS_WIN ? path.join(venv, "Scripts", "python.exe") : path.join(venv, "bin", "python"),
        ["-m", "pip", "install", "--quiet", "--disable-pip-version-check", SPEC]],
    ]) {
      const r = spawnSync(step[0], step[1], { stdio: "inherit", shell: IS_WIN });
      if (r.status !== 0) {
        fs.rmSync(venv, { recursive: true, force: true });
        console.error("pdfdown: installation failed (see the messages above).");
        process.exit(1);
      }
    }
  }
  run(exe, ARGS);
}

function findUvx() {
  if (has("uvx")) return "uvx";
  const home = os.homedir();
  for (const dir of [path.join(home, ".local", "bin"), path.join(home, ".cargo", "bin")]) {
    const exe = path.join(dir, IS_WIN ? "uvx.exe" : "uvx");
    if (fs.existsSync(exe)) return exe;
  }
  return null;
}

// Install what is missing with the same installer as the website one-liner, in "dependencies only" mode:
// on Windows the Visual C++ Runtime (PyTorch needs it) and uv; elsewhere uv. uv brings its own Python.
function installDependencies() {
  const env = { ...process.env, PDFDOWN_DEPS_ONLY: "1" };
  const here = path.join(__dirname, "..");
  console.error("pdfdown: installing what pdfdown needs (one time only) ...");
  const r = IS_WIN
    ? spawnSync("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(here, "install.ps1")],
                { stdio: "inherit", env })
    : spawnSync("sh", [path.join(here, "install.sh")], { stdio: "inherit", env });
  return r.status === 0;
}

function windowsRuntimeChecked() {
  // Check the Visual C++ Runtime once per version; uv may be there already while the runtime is not.
  const marker = path.join(process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache"), "pdfdown-npm",
                           `${VERSION}.deps`);
  if (fs.existsSync(marker)) return;
  if (installDependencies()) {
    fs.mkdirSync(path.dirname(marker), { recursive: true });
    fs.writeFileSync(marker, "ok\n");
  }
}

const forced = process.env.PDFDOWN_LAUNCHER;
if (IS_WIN && !forced) windowsRuntimeChecked();
let uvx = forced === "venv" ? null : findUvx();
if (!uvx && !forced && !findPython()) {
  installDependencies();
  uvx = findUvx();
}
if (uvx) {
  run(uvx, ["--python", "3.12", "--from", SPEC, "pdfdown", ...ARGS]);
} else {
  viaVenv();
}
