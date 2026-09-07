// CLAUDE.md: version chip, release notes, package metadata and API agree.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const changelog = read("../src/changelog.ts");
const version = changelog.match(/export const APP_VERSION = "([^"]+)"/)?.[1];
assert.match(version || "", /^\d+\.\d+\.\d+$/, "APP_VERSION must be a release version");
const pkg = JSON.parse(read("../package.json"));
const lock = JSON.parse(read("../package-lock.json"));
const versions = {
  "package.json": pkg.version,
  "package-lock.json": lock.version,
  "package-lock root": lock.packages[""].version,
  "backend package": read("../../backend/zargar/__init__.py").match(/__version__\s*=\s*"([^"]+)"/)?.[1],
  "pyproject.toml": read("../../backend/pyproject.toml").match(/^version\s*=\s*"([^"]+)"/m)?.[1],
  "latest changelog entry": changelog.match(/version:\s*"([^"]+)"/)?.[1],
};
for (const [source, value] of Object.entries(versions)) assert.equal(value, version, `${source} must match APP_VERSION`);
console.log(`Release ${version}: UI, changelog, backend and package metadata agree`);
