import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const data = JSON.parse(fs.readFileSync("docs/km-modernization/progress/data/2026-W34.json", "utf8"));
const wp1 = data.work_packages.find((wp) => wp.id === "WP1");

assert.equal(wp1.progress, 100);
assert.equal(wp1.tests, true);
assert.equal(wp1.acceptance, true);
assert.equal(wp1.production_gate, "PASS");
assert.equal(wp1.merged, false);
assert.equal(wp1.integration.status, "completed");
assert.equal(wp1.integration.method, "fast-forward");
assert.equal(wp1.integration.compare.status, "identical");
assert.equal(wp1.integration.compare.ahead_by, 0);
assert.equal(wp1.integration.compare.behind_by, 0);
assert.match(wp1.integration.target_sha, /^[0-9a-f]{40}$/);
assert.ok(wp1.integration.evidence_path);

execFileSync("node", ["scripts/generate_weekly_pptx.mjs", "--week", "2026-W34", "--validate"], { stdio: "inherit" });
console.log("canonical weekly validator contract PASS");
