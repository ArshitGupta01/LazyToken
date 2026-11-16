"use strict";

// Build a publishable package from the current checkout without changing source files.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const destination = process.argv[2] && path.resolve(process.argv[2]);
if (!destination || fs.existsSync(destination)) {
  console.error("Usage: node npm/stage.cjs <new-package-directory>");
  process.exit(1);
}
fs.mkdirSync(destination, { recursive: true });
for (const name of ["package.json", "launcher.cjs", "README.md"]) {
  fs.copyFileSync(path.join(__dirname, name), path.join(destination, name));
}
const runtime = path.join(destination, "runtime");
fs.mkdirSync(runtime);
const files = [
  "app_entry.py", "broker.py", "dashboard.py", "data_ops.py", "diagnostics.py",
  "features.py", "frameworks.py", "kn.py", "learning.py", "mcp_schema.py", "migration.py",
  "onboarding.py", "retrieval_eval.py", "source_index.py", "token_budget.py", "watcher.py",
  "index.html", "styles.css", "app.js", "features-ui.js", "graph3d.js", "POLICY.md", "LICENSE",
  "vendor/OrbitControls.js", "vendor/three.core.js", "vendor/three.module.js", "vendor/THREE-LICENSE.txt",
  "benchmark/__init__.py", "benchmark/harness.py", "benchmark/corpus.json",
];
for (const name of files) {
  const target = path.join(runtime, name);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(path.join(root, name), target);
}
console.log(`Staged LazyToken npm package at ${destination}`);
