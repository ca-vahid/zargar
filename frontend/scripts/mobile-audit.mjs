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
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const OUT = path.join(ROOT, "frontend", ".mobile-shots");
fs.mkdirSync(OUT, { recursive: true });

const ROUTES = ["/armed", "/trade", "/inbox", "/portfolios", "/", "/options",
  "/watchlists", "/journal", "/settings", "/technique"];
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
  const wide = [...document.querySelectorAll('body *')].filter(el => vis(el) && el.getBoundingClientRect().width > vw + 2 && getComputedStyle(el).position !== 'fixed').slice(0, 15).map(el => label(el) + ' w=' + Math.round(el.getBoundingClientRect().width));
  const interactive = [...document.querySelectorAll('button, a[href], [role=button], [role=option], [role=tab], input, select, textarea, summary')].filter(vis);
  const tiny = interactive.filter(el => { const r = el.getBoundingClientRect(); return r.height < 40 || r.width < 40; }).map(el => label(el) + ' ' + Math.round(el.getBoundingClientRect().width) + 'x' + Math.round(el.getBoundingClientRect().height));
  const zoomInputs = [...document.querySelectorAll('input, select, textarea')].filter(el => vis(el) && parseFloat(getComputedStyle(el).fontSize) < 16).map(el => label(el) + ' ' + getComputedStyle(el).fontSize);
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
  const page = await ctx.newPage();
  for (const route of m.routes ?? ROUTES) {
    const key = `${m.name} ${route}`;
    try {
      await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 30000 });
      await page.waitForTimeout(2500);
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
