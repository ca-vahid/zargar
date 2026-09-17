// Real built app with isolated synthetic API/WS; no engine or trading writes.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile,mkdir} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import {chromium,devices} from 'playwright';
const dist=resolve('dist'); await mkdir('.mobile-shots',{recursive:true});
const server=createServer(async(req,res)=>{
 const path=resolve(dist,new URL(req.url,'http://localhost').pathname.replace(/^\//,''));
 if(!path.startsWith(dist)){res.writeHead(403).end();return;}
 try{res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[extname(path)]||'text/html');res.end(await readFile(path));}
 catch{res.setHeader('Content-Type','text/html');res.end(await readFile(resolve(dist,'index.html')));}
});await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`, browser=await chromium.launch({headless:true});
const result={account:'Options Cartel Practice',session:'2026-09-14',baseCurrency:'USD',totals:{netRealized:-61.13,grossRealized:-59.05,realizedFees:2.08},closedCampaigns:1,openInstruments:0,entryOrders:1,exitOrders:1,note:'Actual executions and fees.',issues:[],rows:[{planId:'apa',symbol:'APA',category:'closed',exitReasons:['cartel:stop'],decisions:[],recoveries:[],assets:[{netRealized:-61.13,remainingQty:0}]}],candidates:[{symbol:'HOG',status:'plan_blocked',reason:'Opening history incomplete',volumeCoverage:{available:18,expected:26}}],attempts:[{id:'one',symbol:'OKTA',status:'expired',at:Date.now(),reason:'Entry window ended'}],fillEvidence:[],missingFillEvidence:2};
result.rows.push({planId:'qs',symbol:'QS',category:'execution_rejected',exitReasons:[],decisions:[],recoveries:[],assets:[],latestExecutionCheck:{reasons:['Final option spread exceeds the saved 20% limit.']},executionChecks:[{at:Date.now(),passed:false,reasons:['Final option spread exceeds the saved 20% limit.'],expression:{symbol:'QS261120P00007000',bid:1.86,ask:2.39}}]});

try{
 for(const [name,device] of [['desktop',{viewport:{width:1440,height:1000}}],['phone',devices['iPhone SE']]]){
  for(const theme of ['light','dark']){
   const page=await browser.newPage(device),errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
   await page.routeWebSocket('**/ws**',socket=>socket.send(JSON.stringify({t:'snapshot',d:{settings:{'trading.mode':'practice','ui.theme':theme},portfolios:[],positions:[],quotes:{},watchlists:[],openOrders:[],proposals:[],halt:{engaged:false,books:{}},broker:{mode:'practice',feedConnected:true}}})));
   await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url());let data=[];
    if(route.request().method()!=='GET')writes.push(url.pathname);
    if(url.pathname.startsWith('/api/auth/'))data={required:false,user:null};
    else if(url.pathname==='/api/options-cartel/preparation')data={configuration:{enabled:false,workspace:'practice',portfolioId:'',budget:500,riskPct:10},latest:null};
    else if(url.pathname==='/api/options-cartel/review-accounts')data=[{id:'archived',name:'Practice archived'}];
    else if(url.pathname==='/api/options-cartel/session-review')data=result;
    else if(url.pathname==='/api/options-cartel/quote-coverage')data={note:'Durable archive',rows:[{planId:'apa',contract:'APA261016C00045000',eligible:1346,observations:1400,gapCount:113,maxGapMs:222641}]};
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
   });
   await page.goto(base+'/techniques/options-cartel');await page.locator('.splash').waitFor({state:'detached'});
   await page.getByText('Daily review · trades, costs and missed opportunities',{exact:true}).click();
   await page.getByRole('button',{name:'Load daily review',exact:true}).click();
   await page.getByText('Net realized -$61.13',{exact:true}).waitFor();
   await page.getByText('Final option spread exceeds the saved 20% limit.',{exact:true}).waitFor();
   assert.equal(await page.getByRole('link',{name:'APA',exact:true}).getAttribute('href'),'/techniques/options-cartel/run/apa');
   await page.getByText('Preparation exclusions and pending plans · 1',{exact:true}).click();
   await page.getByText(/HOG/).waitFor();
   await page.getByText('Recorded option coverage',{exact:true}).click();
   assert(await page.getByText(/1346\/1400/).isVisible());
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.screenshot({path:`.mobile-shots/cartel-eod-${name}-${theme}.png`,fullPage:true});
   await page.getByLabel('Review session').fill('2026-09-13');
   assert.equal(await page.getByText('Net realized -$61.13',{exact:true}).count(),0);
   assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);await page.close();
   console.log(`PASS ${name} ${theme}: net fees, outcomes, exclusions, archive coverage, URL, scope reset, no writes`);
  }
 }
}finally{await browser.close();await new Promise(r=>server.close(r));}
