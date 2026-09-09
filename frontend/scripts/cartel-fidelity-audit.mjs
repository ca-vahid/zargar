// Isolated UI contract test: static build + synthetic API/WebSocket responses. No engine.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, mkdir} from 'node:fs/promises';
import {resolve, extname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium, devices} from 'playwright';

const dist = fileURLToPath(new URL('../dist/', import.meta.url));
const output = fileURLToPath(new URL('../.mobile-shots/', import.meta.url));
await mkdir(output, {recursive:true});
const server = createServer(async (req,res) => {
  const relative = new URL(req.url, 'http://localhost').pathname;
  const path = resolve(dist, relative.replace(/^\//,''));
  if (!path.startsWith(resolve(dist))) { res.writeHead(403).end(); return; }
  const mime = {'.js':'text/javascript','.css':'text/css','.png':'image/png','.webp':'image/webp','.svg':'image/svg+xml','.html':'text/html'};
  try { res.setHeader('Content-Type', mime[extname(path)] || 'application/octet-stream'); res.end(await readFile(path)); }
  catch { res.setHeader('Content-Type','text/html'); res.end(await readFile(resolve(dist,'index.html'))); }
});
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({headless:true});
try {
  for (const [device, options] of [['desktop',{viewport:{width:1440,height:1000}}],['phone',devices['iPhone 14']]]) {
    for (const workspace of ['practice','live']) {
      const page = await browser.newPage(options);
      const errors=[]; page.on('pageerror',e=>errors.push(e.message));
      let saved;
      const config={enabled:false,workspace,allowLive:false,overnightAck:false,portfolioId:workspace,
        profile:'september_2026',scanAll:true,historyLimit:200,focusCount:5,budget:500,riskPct:10,
        industryPolicy:'context',reviewedEtfs:['DRAM'],comparisonSymbols:['MU'],comparisonSource:'Synthetic dated watchlist',
        entry:{timeframe_minutes:15,mode:'breakout',allow_gap_retest:true,volume_multiple:1.5,min_close_location:.7},
        exitProfile:'september_2026',horizonSessions:1,septemberFractions:[.25,.25,.2,.2,.1],allowFibonacciTargets:true};
      await page.routeWebSocket('**/ws**',socket=>socket.send(JSON.stringify({t:'snapshot',d:{
        settings:{'trading.mode':workspace,'techniques.options_cartel.default_portfolio':'practice'},
        portfolios:[{id:'practice',name:'Cartel Practice',kind:'sim',currency:'USD',baseCurrency:'USD',cash:10000,equity:10000},
          {id:'live',name:'Synthetic Live',kind:'live',currency:'USD',baseCurrency:'USD',cash:10000,equity:10000}],
        positions:[],openOrders:[],quotes:{},watchlists:[],proposals:[],halt:{halted:false},broker:{connected:true},
      }})));
      await page.route('**/api/**',async route=> {
        const url=new URL(route.request().url()); let data=[];
        if(url.pathname.startsWith('/api/auth/')) data={required:false,user:null};
        else if(url.pathname.includes('/preparation')) {
          if(route.request().method()==='POST') saved=route.request().postDataJSON();
          data={configuration:saved||config,latest:{runId:'research-fixture',status:'done',result:{phase:'complete',armingBlocked:true,researchDirection:'long',researchCandidates:1,discovered:1,evaluated:1,notEvaluated:0,dataErrors:0,qualifying:0,armed:0,coverageComplete:true,rows:[],shortlist:[{symbol:'TEST',analysisId:'research-analysis',status:'market_blocked',reason:'Research only: market alignment blocks arming'}],market:{direction:'mixed',reason:'Both indices must agree',indices:{SPY:{direction:'mixed',session:'2026-09-08',close:100,emas:{8:101,21:99},aboveEmas:{8:false,21:true}}}}}},liveAutoAllowed:false,activation:{},quoteRefresh:{errors:{}}};
        } else if(url.pathname.endsWith('/schedule')) data={configuration:{scanSymbols:[]},jobs:[]};
        else if(url.pathname.endsWith('/quote-recording')) data={enabled:false,errors:{},captured:0};
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
      });
      await page.goto(`${base}/techniques/options-cartel/settings`);
      await page.locator('.splash').waitFor({state:'detached'});
      await page.getByRole('combobox',{name:/^Industry policy/}).selectOption('strict');
      await page.getByLabel('History batch size',{exact:true}).fill('50');
      await page.getByLabel('Parallel history fetches',{exact:true}).fill('8');
      await page.getByLabel('Reviewed ETF symbols',{exact:true}).fill('DRAM, TEST');
      await page.getByRole('combobox',{name:/^Confirmation timeframe/}).selectOption('5');
      await page.getByRole('combobox',{name:/^Entry approach/}).selectOption('retest');
      await page.getByRole('button',{name:'Save preparation settings',exact:true}).click();
      await page.getByText('Cartel preparation settings saved',{exact:true}).waitFor();
      assert.equal(saved.workspace,workspace);
      assert.equal(saved.industryPolicy,'strict');
      assert.equal(saved.historyBatchSize,50); assert.equal(saved.historyConcurrency,8);
      assert.deepEqual(saved.reviewedEtfs,['DRAM','TEST']);
      assert.equal(saved.entry.timeframe_minutes,5); assert.equal(saved.entry.mode,'retest');
      assert.equal(saved.allowLive,false); assert.equal(saved.enabled,false);
      assert.deepEqual(errors,[]);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1),'document overflow');
      await page.getByRole('tab',{name:'Plans',exact:true}).click();
      await page.getByRole('region',{name:'Market alignment',exact:true}).waitFor();
      assert.equal(await page.getByText(/Coverage incomplete:/).count(),0);
      assert((await page.getByRole('link',{name:'Open TEST',exact:true}).getAttribute('href')).endsWith('/run/research-analysis'));
      await page.screenshot({path:resolve(output,`cartel-fidelity-${device}-${workspace}.png`),fullPage:true});
      console.log(`PASS ${device} ${workspace}: controls, save payload, disabled execution, research-only market banner, no overflow`);
      await page.close();
    }
  }
} finally {await browser.close(); await new Promise(resolve=>server.close(resolve));}
