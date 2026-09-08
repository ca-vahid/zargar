// UI contract test: mocked progress responses, real app rendering. No writes to the engine.
import assert from "node:assert/strict";
import { chromium, devices } from "playwright";

const base = process.argv[2] || "http://127.0.0.1:8421";
const browser = await chromium.launch({headless:true});
try {
  for (const [name, options] of [["desktop", {viewport:{width:1440,height:1000}}], ["phone", devices["iPhone 14"]]]) {
    const page = await browser.newPage(options);
    const errors = []; page.on("pageerror", e => errors.push(e.message));
    const source = await (await page.request.get(`${base}/api/options-cartel/preparation?workspace=practice`)).json();
    let phase = "discovering", planReads = 0;
    const at = Date.now();
    await page.route("**/api/options-cartel/preparation?*", route => route.fulfill({status:200, contentType:"application/json", body:JSON.stringify({
      ...source, canResume:phase === "interrupted", configuration:{...source.configuration, enabled:true, scanAll:true}, serverNow:Date.now(),
      latest:{runId:"progress-fixture", status:phase === "complete" ? "done" : phase === "interrupted" ? "failed" : "running", result:{
        phase, message:phase === "discovering" ? "Received 250 of 3087 listings" : "Checking TEST evidence",
        session:"2026-09-08", startedAt:at, updatedAt:Date.now(), finishedAt:phase === "complete" ? Date.now() : undefined,
        discoveryProgress:{received:250,total:3087}, discovered:3087, evaluationTotal:3087, processed:205,
        prefiltered:200, evaluated:5, dataErrors:0, qualifying:0, armed:0, currentSymbol:"TEST", rows:[], shortlist:[],
      }},
    })}));
    await page.route("**/api/options-cartel/runs?*", route => {
      if (new URL(route.request().url()).searchParams.get("mode") !== "plan") return route.continue();
      planReads++;
      return route.fulfill({status:200, contentType:"application/json", body:JSON.stringify(phase === "complete" ? [{
        runId:"saved-fixture", symbol:"TEST", mode:"plan", status:"done", verdict:"plan", createdAt:new Date(at).toISOString(), asOfMs:at,
      }] : [])});
    });
    await page.goto(`${base}/techniques/options-cartel`);
    await page.locator(".splash").waitFor({state:"detached"});
    const discovery = page.getByRole("progressbar", {name:"Discovery progress", exact:true});
    await discovery.waitFor(); assert.equal(await discovery.getAttribute("value"), "250");
    phase = "evaluating";
    const evaluation = page.getByRole("progressbar", {name:"Stock evaluation progress", exact:true});
    await evaluation.waitFor(); assert.equal(await evaluation.getAttribute("value"), "205");
    const before = planReads;
    phase = "complete";
    await page.getByRole("link", {name:"Open TEST", exact:true}).waitFor();
    assert(planReads > before, "Completion must refresh the separate saved-plan list");
    phase = "interrupted";
    let resumeId = null;
    await page.route("**/api/options-cartel/preparation/run?*", route => {
      resumeId = new URL(route.request().url()).searchParams.get("resumeRunId");
      phase = "evaluating";
      return route.fulfill({status:202, contentType:"application/json", body:'{"status":"running"}'});
    });
    await page.reload();
    await page.getByRole("button", {name:"Resume saved scan", exact:true}).click();
    await page.getByRole("progressbar", {name:"Stock evaluation progress", exact:true}).waitFor();
    assert.equal(resumeId, "progress-fixture");
    await page.getByRole("tab", {name:"Settings", exact:true}).click();
    const all = page.getByLabel("Evaluate all eligible stocks", {exact:true});
    await all.waitFor(); assert(await all.isChecked());
    assert.equal(await page.getByLabel("Optional symbol cap", {exact:true}).count(), 0);
    await all.uncheck(); await page.getByLabel("Optional symbol cap", {exact:true}).waitFor();
    assert.deepEqual(errors, []);
    console.log(`PASS ${name}: discovery/evaluation progress, automatic saved-plan refresh, resume action, optional cap`);
    await page.close();
  }
} finally { await browser.close(); }
