"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { test } = require("node:test");

test("transient npm cache refuses to save a temporary MCP path", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "toksmart-launcher-"));
  try {
    const cached = path.join(tmp, "_npx", "package");
    fs.mkdirSync(cached, { recursive: true });
    fs.copyFileSync(path.join(__dirname, "launcher.cjs"), path.join(cached, "launcher.cjs"));
    const result = spawnSync(process.execPath, [path.join(cached, "launcher.cjs"), "setup", "--apply"], { encoding: "utf8" });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /durable installation/);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test("launcher accepts serve command and passes through options", () => {
  const result = spawnSync(process.execPath, [path.join(__dirname, "launcher.cjs"), "serve", "--help"], {
    encoding: "utf8",
  });
  assert.equal(result.status, 0);
  assert.match(result.stdout, /Loopback-only browser dashboard/);
  assert.match(result.stdout, /--port/);
});
