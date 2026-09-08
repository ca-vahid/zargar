// Read-only regression for duplicated charts and dedicated record navigation.
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const base = process.argv[2] || "http://127.0.0.1:8421";
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = []; page.on("pageerror", e => errors.push(e.message));
  const plans = await (await page.request.get(`${base}/api/options-cartel/runs?mode=plan&workspace=practice&limit=100`)).json();
  const plan = plans.find(p => p.symbol === "SPCX") || plans[0];
  assert(plan, "A saved plan fixture is required");
  const url = `${base}/techniques/options-cartel/run/${plan.runId}`;
  const heading = () => page.getByRole("heading", {name:`${plan.symbol} · plan`, exact:true});
  const singleChart = async () => {
    assert.equal(await page.locator('[aria-label="Saved Cartel chart"]').count(), 1);
    assert.equal(await page.locator('.highcharts-container').count(), 1);
  };
  await page.goto(`${base}/techniques/options-cartel`);
  await page.locator('.splash').waitFor({state:'detached'});
  const link = page.locator(`tr[data-run-id="${plan.runId}"]`).getByRole('link', {name:`Open ${plan.symbol}`,exact:true});
  assert.equal(await link.getAttribute('href'), `/techniques/options-cartel/run/${plan.runId}`);
  const opened = page.context().waitForEvent('page');
  await link.click({modifiers:['Control']});
  const separate = await opened;
  await separate.getByRole('heading',{name:`${plan.symbol} · plan`,exact:true}).waitFor();
  assert.equal(separate.url(),url); await separate.close();
  await link.click(); await page.waitForURL(url); await heading().waitFor();
  assert.equal(await page.getByRole('region',{name:'Daily preparation',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Arm alert only',exact:true}).isVisible(),false);
  await page.getByRole('region',{name:'Plan explanation',exact:true}).waitFor();
  for(let i=0;i<8;i++) {
    const loaded = page.waitForResponse(r => r.url() === `${base}/api/options-cartel/runs/${plan.runId}`);
    await page.getByRole('button',{name:'Refresh record',exact:true}).click(); await loaded;
    await heading().waitFor(); await singleChart();
  }
  for(const name of ['60 sessions','All saved sessions','30 sessions']) {
    await page.getByRole('button',{name,exact:true}).click(); await singleChart();
  }
  await page.reload(); await heading().waitFor(); assert.equal(page.url(),url); await singleChart();
  await page.getByRole('button',{name:'← Back',exact:true}).click();
  await page.getByRole('tab',{name:'Plans',exact:true}).waitFor();
  await page.goForward(); await heading().waitFor(); await singleChart();
  await page.screenshot({path:fileURLToPath(new URL('../.mobile-shots/cartel-record-desktop.png',import.meta.url)), fullPage:false});
  const direct = await browser.newPage();
  await direct.goto(url); await direct.getByRole('heading',{name:`${plan.symbol} · plan`,exact:true}).waitFor();
  await direct.getByRole('button',{name:'← Back',exact:true}).click();
  await direct.getByRole('tab',{name:'Plans',exact:true}).waitFor();
  await direct.close();
  const missing = await browser.newPage();
  await missing.goto(`${base}/techniques/options-cartel/run/does-not-exist`);
  await missing.getByRole('alert').waitFor();
  assert.equal(await missing.locator('.highcharts-container').count(),0);
  await missing.getByRole('button',{name:'← Back',exact:true}).click();
  await missing.getByRole('tab',{name:'Plans',exact:true}).waitFor();
  await missing.close();
  assert.deepEqual(errors,[]);
  console.log('PASS: dedicated URL, direct load, reload, back/forward, manual-controls separation, eight refreshes and range changes retain one chart');
} finally {await browser.close();}
