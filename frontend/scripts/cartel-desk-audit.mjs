// Read-only navigation/visual checks against the isolated preview. No settings or orders are submitted.
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const base = process.argv[2] || "http://127.0.0.1:8421";
const out = new URL("../.mobile-shots/", import.meta.url);
mkdirSync(out, {recursive: true});
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width:1440, height:1000}});
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`${base}/techniques/options-cartel`);
  await page.getByRole("region", {name:"Daily preparation", exact:true}).waitFor();
  await page.locator(".splash").waitFor({state:"detached"});
  await page.getByRole("region", {name:"Daily preparation", exact:true}).getByText(/Automatic Practice/).waitFor();
  for (const theme of ["dark", "light"]) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
    await page.screenshot({path: fileURLToPath(new URL(`cartel-desktop-${theme}.png`, out))});
  }
  await page.getByRole("tab", {name:"Plans", exact:true}).focus();
  await page.keyboard.press("ArrowRight");
  await page.getByRole("tab", {name:/^Armed/, selected:true}).waitFor();
  await page.getByRole("tab", {name:"Settings", exact:true}).click();
  await page.getByLabel("Shortlist size", {exact:true}).waitFor();
  assert.equal(await page.getByRole("region", {name:"Daily preparation", exact:true}).count(), 0);
  await page.getByRole("tab", {name:"Plans", exact:true}).click();
  assert.equal(await page.getByLabel("Shortlist size", {exact:true}).count(), 0);
  const response = await page.request.get(`${base}/api/options-cartel/runs?mode=plan&limit=1`);
  assert.ok(response.ok(), "Saved plans endpoint must be available");
  const [plan] = await response.json();
  if (plan) {
    await page.locator(`tr[data-run-id="${plan.runId}"]`).getByRole("button", {name:`Open ${plan.symbol}`, exact:true}).click();
    await page.getByRole("heading", {name:`${plan.symbol} · plan`, exact:true}).waitFor();
    await page.getByRole("button", {name:"Close details", exact:true}).click();
  }
  await page.goto(`${base}/techniques/options-cartel/desk`);
  await page.getByRole("tab", {name:"Plans", exact:true, selected:true}).waitFor();
  const preparation = await (await page.request.get(`${base}/api/options-cartel/preparation`)).json();
  await page.route("**/api/options-cartel/preparation?*", route => route.fulfill({
    status:503, contentType:"application/json", body:JSON.stringify({detail:"Preparation temporarily unavailable"}),
  }));
  await page.reload();
  await page.getByRole("alert").first().waitFor();
  await page.unroute("**/api/options-cartel/preparation?*");
  await page.getByRole("button", {name:"retry", exact:true}).click();
  await page.getByRole("region", {name:"Daily preparation", exact:true}).getByText(/Automatic Practice/).waitFor();
  await page.route("**/api/options-cartel/preparation?*", route => route.fulfill({
    status:200, contentType:"application/json", body:JSON.stringify({...preparation, latest:null}),
  }));
  await page.reload();
  await page.getByText("No preparation yet", {exact:true}).waitFor();
  assert.deepEqual(errors, [], "No browser runtime errors");
  console.log(`PASS: light/dark views, keyboard tabs, settings separation, legacy route, error/retry and empty states${plan ? ", saved-plan details" : " (no saved-plan fixture)"}`);
} finally {
  await browser.close();
}
