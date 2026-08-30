// Render an HTML file to PDF via headless Chromium (used for the knowledge
// system explainer — docs/techniques/tip/knowledge-system-pdf.html).
//   node scripts/render-pdf.mjs <input.html> <output.pdf>
import { chromium } from "playwright";

const [, , src, out] = process.argv;
if (!src || !out) {
  console.error("usage: node scripts/render-pdf.mjs <input.html> <output.pdf>");
  process.exit(1);
}
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto("file:///" + src.replace(/\\/g, "/"), { waitUntil: "networkidle" });
await page.pdf({ path: out, format: "Letter", printBackground: true });
await browser.close();
console.log("wrote", out);
