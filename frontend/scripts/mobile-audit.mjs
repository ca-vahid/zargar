// Mobile audit gate (docs/MOBILE-PLAN.md, Phase 9).
//
// Renders every route on a phone/tablet device matrix, saves screenshots to
// frontend/.mobile-shots/ (gitignored) and audit.json, and FAILS (exit 1) on:
//   - layout viewport wider than the device (the page's min content width)
//   - horizontal document overflow
//   - elements wider than the viewport
//   - inputs/selects/textareas with font-size < 16px (iOS zoom-on-focus)
//   - interactive targets shorter/narrower than 40px on phone routes
//   - title= on interactive elements (hover-only meaning)
//
// One-time setup (kept out of package.json on purpose):
//   cd frontend && npx playwright install chromium   (playwright itself is a devDependency)
// Run against a live app:  cd frontend && npm run mobile-audit [-- baseUrl]
// Baseline-only (no failure): MOBILE_AUDIT_REPORT_ONLY=1 npm run mobile-audit

import { chromium, devices } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.argv[2] ?? "http://127.0.0.1:8420";
const REPORT_ONLY = !!process.env.MOBILE_AUDIT_REPORT_ONLY;
// sign-in is enforced: pass a session from `python -m zargar.tools.mint_session`
// (backend/) as ZARGAR_SESSION, else every route screenshots the login page
const SESSION = process.env.ZARGAR_SESSION ?? "";
// Focused reruns after a route-specific fix; unset retains the complete default audit.
const REQUESTED_ROUTES = process.env.MOBILE_AUDIT_ROUTES?.split(",").map(s => s.trim()).filter(Boolean);
const CARTEL_PLAN = process.env.MOBILE_AUDIT_CARTEL_PLAN;
if (REQUESTED_ROUTES && (!REQUESTED_ROUTES.length || REQUESTED_ROUTES.some(r => !r.startsWith("/")))) {
  throw new Error("MOBILE_AUDIT_ROUTES must contain comma-separated absolute route paths");
}
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const OUT = path.join(ROOT, "frontend", ".mobile-shots");
fs.mkdirSync(OUT, { recursive: true });

const ROUTES = ["/armed", "/trade", "/inbox", "/portfolios", "/", "/options",
  "/watchlists", "/ledger", "/journal", "/settings", "/technique",
  "/techniques/options-cartel", "/techniques/options-cartel/armed", "/techniques/options-cartel/history",
  "/techniques/options-cartel/validation", "/techniques/options-cartel/settings", "/techniques/options-cartel/method"];
const MATRIX = [
  { name: "iphone-se", device: devices["iPhone SE"], phone: true },
  { name: "iphone-14", device: devices["iPhone 14"], phone: true },
  { name: "pixel-7", device: devices["Pixel 7"], phone: true },
  { name: "ipad-mini", device: devices["iPad Mini"], phone: false },
  { name: "iphone-14-landscape", device: devices["iPhone 14 landscape"], phone: true, routes: ["/trade", "/armed"] },
];

const AUDIT = `(() => {
  const vw = window.innerWidth;
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const label = (el) => el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  // a wide element inside a horizontal scroller (scroll-x, table wrap, ladder) is a legitimate
  // scrollable table, not a layout break — only count it when nothing above it scrolls it
  const scrolls = (el) => { for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) { const o = getComputedStyle(a).overflowX; if ((o === 'auto' || o === 'scroll') && a.getBoundingClientRect().width <= vw + 2) return true; } return false; };
  const wide = [...document.querySelectorAll('body *')].filter(el => vis(el) && el.getBoundingClientRect().width > vw + 2 && getComputedStyle(el).position !== 'fixed' && !scrolls(el)).slice(0, 15).map(el => label(el) + ' w=' + Math.round(el.getBoundingClientRect().width));
  const interactive = [...document.querySelectorAll('button, a[href], [role=button], [role=option], [role=tab], input, select, textarea, summary')].filter(vis);
  const tiny = interactive.filter(el => { const r = el.getBoundingClientRect(); return r.height < 40 || r.width < 40; }).map(el => label(el) + ' ' + Math.round(el.getBoundingClientRect().width) + 'x' + Math.round(el.getBoundingClientRect().height));
  const zoomInputs = [...document.querySelectorAll('input, select, textarea')].filter(el => vis(el) && !el.className.toString().includes('highcharts-a11y') && parseFloat(getComputedStyle(el).fontSize) < 16).map(el => label(el) + ' ' + getComputedStyle(el).fontSize);
  const titled = interactive.filter(el => el.hasAttribute('title') && !el.getAttribute('aria-label') && !el.textContent.trim()).map(label);
  const tables = [...document.querySelectorAll('table')].filter(vis).map(t => ({ cols: t.querySelectorAll('thead th').length || (t.rows[0]?.cells.length ?? 0), w: Math.round(t.getBoundingClientRect().width) }));
  return { vw, scrollW: document.documentElement.scrollWidth, overflowX: document.documentElement.scrollWidth > vw + 1,
    wide, tinyCount: tiny.length, tiny: tiny.slice(0, 25), interactiveCount: interactive.length,
    zoomInputs: zoomInputs.slice(0, 25), zoomInputCount: zoomInputs.length, titled: titled.slice(0, 25), tables };
})()`;

const browser = await chromium.launch();
const results = {};
let failures = 0;
for (const m of MATRIX) {
  const ctx = await browser.newContext({ ...m.device, locale: "en-US", timezoneId: "America/New_York" });
  if (SESSION) await ctx.addCookies([{ name: "zargar_session", value: SESSION, url: BASE }]);
  const page = await ctx.newPage();
  for (const route of REQUESTED_ROUTES ?? m.routes ?? ROUTES) {
    const key = `${m.name} ${route}`;
    try {
      // domcontentloaded + a fixed settle, NOT networkidle: pages like
      // /technique poll continuously while the engine runs checks, so the
      // network never goes idle and the audit would flake on live systems
      await page.goto(BASE + route, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForTimeout(3500);
      if (CARTEL_PLAN && route === "/techniques/options-cartel/plans") {
        const response = await page.request.get(`${BASE}/api/options-cartel/runs/${encodeURIComponent(CARTEL_PLAN)}`);
        if (!response.ok()) throw new Error("Cartel audit fixture is unavailable");
        const plan = await response.json();
        await page.locator(`tr[data-run-id="${plan.runId}"]`).getByRole("link", {name: `Open ${plan.symbol}`, exact: true}).click();
        await page.getByText("Manual execution controls", {exact:true}).click();
        await page.getByRole("combobox", {name: "Execution mode", exact: true}).selectOption("proposal");
        await page.getByText("Find an eligible contract", {exact: true}).click();
        await page.getByText("Replay this campaign", {exact: true}).click();
        await page.getByRole("heading", {name: "Arm reviewed plan", exact: true}).scrollIntoViewIfNeeded();
        if (process.env.MOBILE_AUDIT_CARTEL_CHART === "1") {
          await page.locator('[aria-label="Saved Cartel chart"] .highcharts-container').scrollIntoViewIfNeeded();
        }
      }
      if (route === "/techniques/options-cartel/validation") await page.getByText("Compare entry rules", {exact: true}).click();
      if (route === "/techniques/options-cartel/history") {
        if (process.env.MOBILE_AUDIT_CARTEL_RUN) {
          const response = await page.request.get(`${BASE}/api/options-cartel/runs/${encodeURIComponent(process.env.MOBILE_AUDIT_CARTEL_RUN)}`);
          if (!response.ok()) throw new Error("Cartel history fixture unavailable");
          const run = await response.json();
          await page.locator(`tr[data-run-id="${run.runId}"]`).getByRole("link", {name: `Open ${run.symbol}`, exact: true}).click();
          if (run.mode === "scan") await page.getByRole("region", {name:"Focus-list scan results", exact:true}).scrollIntoViewIfNeeded();
          if (run.mode === "industry") await page.getByRole("region", {name:"Industry capture results", exact:true}).scrollIntoViewIfNeeded();
          if (run.mode === "fundamentals" || run.mode === "membership") await page.getByRole("region", {name:"Saved stock evidence", exact:true}).scrollIntoViewIfNeeded();
          if (run.mode === "premium_replay") await page.getByRole("region", {name:"Option replay valuation", exact:true}).scrollIntoViewIfNeeded();
          if (run.mode === "replay" && process.env.MOBILE_AUDIT_CARTEL_PREMIUM === "1") {
            await page.getByText("Value with recorded option quotes", {exact:true}).click();
            await page.getByRole("textbox", {name:"Option contract", exact:true}).scrollIntoViewIfNeeded();
          }
        }
      }
      if (route === "/techniques/options-cartel/settings") {
        await page.getByText("Scheduled scans and recovery", {exact: true}).click();
        if (process.env.MOBILE_AUDIT_CARTEL_RECORDING === "1") {
          await page.getByText("Option quote recording", {exact:true}).click();
          await page.getByRole("button", {name:"Save recording setting", exact:true}).scrollIntoViewIfNeeded();
        }
      }
      if (route === "/techniques/options-cartel/validation") {
        if (process.env.MOBILE_AUDIT_CARTEL_INDUSTRY === "1") await page.getByText("Import an industry capture", {exact:true}).click();
        if (process.env.MOBILE_AUDIT_CARTEL_EVIDENCE === "1") {
          await page.getByRole("textbox", {name:"Symbol", exact:true}).fill("MU");
          await page.getByText("Fundamental and industry evidence", {exact:true}).click();
          if (process.env.MOBILE_AUDIT_CARTEL_MEMBERSHIP) {
            await page.getByRole("combobox", {name:"Saved industry membership", exact:true})
              .selectOption(process.env.MOBILE_AUDIT_CARTEL_MEMBERSHIP);
            await page.getByRole("button", {name:"Use manual industry mapping", exact:true}).waitFor();
          }
          await page.getByRole("combobox", {name:"Saved industry membership", exact:true}).scrollIntoViewIfNeeded();
        }
      }
      if (route === "/techniques/options-cartel/method" && process.env.MOBILE_AUDIT_CARTEL_CHAPTER) {
        await page.getByRole("combobox", {name:"Read a chapter", exact:true}).selectOption(process.env.MOBILE_AUDIT_CARTEL_CHAPTER);
      }
      const shot = path.join(OUT, `${m.name}${route === "/" ? "-dashboard" : route.replace(/\//g, "-")}.png`);
      await page.screenshot({ path: shot, fullPage: false });
      const r = await page.evaluate(AUDIT);
      const problems = [];
      const deviceW = m.device.viewport.width;
      // mobile browsers widen the layout viewport to the page's minimum content
      // width and zoom out — the app's ~760px layout floor shows up here
      if (r.vw > deviceW + 2) problems.push(`layout floor: page laid out at ${r.vw}px on a ${deviceW}px device`);
      if (r.overflowX) problems.push(`horizontal overflow (${r.scrollW} > ${r.vw})`);
      if (r.wide.length) problems.push(`${r.wide.length} elements wider than viewport`);
      if (r.zoomInputCount) problems.push(`${r.zoomInputCount} inputs < 16px`);
      if (m.phone && r.tinyCount) problems.push(`${r.tinyCount}/${r.interactiveCount} targets < 40px`);
      if (r.titled.length) problems.push(`${r.titled.length} icon-only controls rely on title=`);
      results[key] = { ...r, problems };
      if (problems.length) failures++;
      console.log(`${problems.length ? "FAIL" : " ok "} ${key}${problems.length ? " — " + problems.join("; ") : ""}`);
    } catch (e) {
      results[key] = { error: String(e).slice(0, 200) };
      failures++;
      console.log(`ERR  ${key} — ${String(e).slice(0, 120)}`);
    }
  }
  await ctx.close();
}
await browser.close();
fs.writeFileSync(path.join(OUT, "audit.json"), JSON.stringify(results, null, 2));
console.log(`\n${failures} failing route/device combos. Screenshots + audit.json in ${OUT}`);
if (failures && !REPORT_ONLY) process.exit(1);
