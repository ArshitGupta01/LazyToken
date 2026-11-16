#!/usr/bin/env node
"use strict";

const { spawnSync } = require("node:child_process");
const { existsSync } = require("node:fs");
const { join, sep } = require("node:path");

if (__dirname.split(sep).some((part) => part.toLowerCase() === "_npx") &&
    process.argv[2] === "setup" && process.argv.includes("--apply")) {
  console.error("MCP setup needs a durable installation. Run 'npm install --global lazytoken', then 'lazytoken setup --apply ...'.");
  process.exit(1);
}

const candidates = process.platform === "win32"
  ? [["py", "-3"], ["python"], ["python3"]]
  : [["python3"], ["python"]];
const check = "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)";
const python = candidates.find(([command, ...prefix]) =>
  spawnSync(command, [...prefix, "-c", check], { stdio: "ignore", windowsHide: true }).status === 0
);

if (!python) {
  console.error("LazyToken needs Python 3.11 or newer. Install Python, then run this command again.");
  process.exit(1);
}

const entryPath = existsSync(join(__dirname, "runtime", "app_entry.py"))
  ? join(__dirname, "runtime", "app_entry.py")
  : join(__dirname, "..", "app_entry.py");

const [command, ...prefix] = python;
const result = spawnSync(command, [...prefix, entryPath, ...process.argv.slice(2)], {
  stdio: "inherit",
  windowsHide: true,
});
if (result.error) {
  console.error(`Unable to start LazyToken: ${result.error.message}`);
  process.exit(1);
}
if (result.signal) process.kill(process.pid, result.signal);
process.exit(result.status ?? 1);
