// Built UI and synthetic data only. No trading engine or runtime database.
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createServer} from 'node:http';
import {readFile,mkdir} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import {chromium,devices} from 'playwright';

async function moduleAt(path) {
  const result=await build({entryPoints:[path],bundle:true,write:false,format:'esm',platform:'node'});
  return import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'));
}
const {attentionSummary,cleanAttentionText}=await moduleAt('src/lib/armedAttention.ts');
const {parseLocation,buildPath}=await moduleAt('src/lib/routing.ts');
assert.deepEqual(parseLocation('/armed/attention'),{page:'armed',pageTab:'attention'});
assert.equal(buildPath({page:'armed',pageTab:'attention'}),'/armed/attention');
assert.deepEqual(parseLocation('/armed/actual-run'),{page:'armed',armedRunId:'actual-run'});
assert.equal(cleanAttentionText('a\\u2014b'),'a—b');
const trigger=(id,entry)=>({id,label:null,kind:'bounce',status:'fired',entry,stop:entry-1,targets:[entry+2],riskReward:2,skipped:[],conditions:[]});
const trade=(id)=>({triggerId:id,kind:'bounce',status:'failed',filledQty:0,remaining:0,entry:85.89,targets:[88],trimsDone:0,exits:[],errors:[]});
function plan(id,symbol,kind='sim') {return {runId:id,symbol,technique:'enhanced_market',status:'armed',planFor:'2026-09-14',
  portfolio:{id:kind,name:kind==='sim'?'EM Practice':'Live account',kind},config:{mode:'auto',instrument:'options',contracts:1},
  triggers:[trigger('b1',85.89),trigger('b2',84.52)],trades:[trade('b1'),trade('b2')],events:[],fired:[],openPositions:0,realizedPnl:0,
  summary:'Nothing left to watch',sessionWindowNow:'prime_open',stale:false,barAgeSeconds:1,needsAttention:true,
  attentionReasons:['b1: fire produced nothing — resulting position 86.6% of equity exceeds 50.0%', 'b2: fire produced nothing \\u2014 resulting position 84.7% of equity exceeds 50.0%']};}
const swks=plan('one','SWKS'),second=plan('two','BBB','live');
second.trades=[{...trade('b1'),status:'open',filledQty:1,remaining:1}];second.openPositions=1;second.attentionReasons=['b1: exit stop failed — 1 still held'];
const normal={...plan('three','AAPL'),needsAttention:false,attentionReasons:[]};
assert(attentionSummary(swks).notice);assert.equal(attentionSummary(swks).items[0].setup,'Support entry at 85.89');
assert(!attentionSummary(second).notice);
assert(!attentionSummary({...swks,trades:[],attentionReasons:['submission outcome unknown']}).notice);
assert(!attentionSummary({...swks,trades:[{...trade('b1'),status:'submitting'}]}).notice);
const dist=resolve('dist');await mkdir('.mobile-shots',{recursive:true});
const server=createServer(async(req,res)=>{
 const path=resolve(dist,new URL(req.url,'http://localhost').pathname.replace(/^\//,''));
 if(path!==dist&&!path.startsWith(dist+'/')&&!path.startsWith(dist+'\\')) {res.writeHead(403).end();return;}
 try{res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml'})[extname(path)]||'text/html');res.end(await readFile(path));}
 catch{res.setHeader('Content-Type','text/html');res.end(await readFile(resolve(dist,'index.html')));}
});await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`,browser=await chromium.launch({headless:true});
try {
 for(const [name,options] of [['desktop',{viewport:{width:1440,height:1000}}],['phone',devices['iPhone SE']]]) {
  for(const theme of ['light','dark']) {
   const page=await browser.newPage(options),errors=[],writes=[];let rows=[swks,second,normal],fail=false;
   page.on('pageerror',e=>errors.push(e.message));
   await page.routeWebSocket('**/ws**',socket=>socket.send(JSON.stringify({t:'snapshot',d:{settings:{'trading.mode':'practice','ui.theme':theme},portfolios:[{id:'sim',kind:'sim',name:'EM Practice',cash:10000,baseCurrency:'USD'}],positions:[],quotes:{},watchlists:[],openOrders:[],proposals:[],halt:{engaged:false,books:{}},broker:{mode:'practice',feedConnected:true}}})));
   await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url());let data=[];
    if(route.request().method()!=='GET') writes.push(url.pathname);
    if(url.pathname.startsWith('/api/auth/'))data={required:false,user:null};
    else if(url.pathname==='/api/technique/armed'){if(fail){await route.fulfill({status:503,body:'temporarily unavailable'});return;}data=rows;}
    else if(url.pathname==='/api/techniques')data=[{id:'enhanced_market',label:'EM Options',page:'technique',tabs:[]}];
    else if(url.pathname==='/api/technique/armed/summary')data={asOf:Date.now(),workspace:'practice',window:'prime_open',counts:{armed:2,paused:0,inTrade:0,attention:1},attention:[],watching:[],timeline:[],inTrade:[],stoppedToday:[],pnl:{realized:0,unrealized:0,lossLimit:0}};
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
   });
   await page.goto(base+'/armed/attention');await page.locator('.splash').waitFor({state:'detached'});
   await page.getByRole('heading',{name:'2 plans to review',exact:true}).waitFor();
   assert.equal(await page.locator('article[aria-label$="attention plan"]').count(),2);
   assert(await page.getByRole('heading',{name:'SWKS',exact:true}).isVisible());
   assert(await page.getByRole('heading',{name:'BBB',exact:true}).isVisible());
   assert.equal(await page.getByRole('heading',{name:'AAPL',exact:true}).count(),0);
   assert(await page.getByText('Support entry at 84.52',{exact:true}).isVisible());
   assert(!(await page.locator('body').innerText()).includes('\\u2014'));
   assert.equal(await page.getByRole('button',{name:'Review BBB plan and orders',exact:true}).count(),0);
   assert(await page.getByText(/Switch to Live using the workspace selector/).isVisible());
   await page.getByRole('button',{name:'Review SWKS plan and orders',exact:true}).click();
   assert(await page.locator('.tq-armed-card').isVisible());
   await page.getByRole('button',{name:'Hide SWKS plan and orders',exact:true}).click();
   await page.getByRole('tab',{name:/^Live/}).click();
   const chip=page.locator(name==='phone'?'.topbar-attn':'.attention-chip').first();await chip.focus();await chip.press('Enter');
   assert.equal(new URL(page.url()).pathname,'/armed/attention');
   await page.getByRole('heading',{name:'2 plans to review',exact:true}).waitFor();
   assert.equal(await chip.evaluate(e=>getComputedStyle(e).animationName),'none');
   await page.goBack();assert.equal(new URL(page.url()).pathname,'/armed');
   await page.goForward();await page.getByRole('heading',{name:'2 plans to review',exact:true}).waitFor();
   await page.reload();await page.getByRole('heading',{name:'2 plans to review',exact:true}).waitFor();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.screenshot({path:`.mobile-shots/attention-${name}-${theme}.png`,fullPage:true});
   fail=true;await page.reload();await page.getByRole('alert').filter({hasText:'Could not refresh plans'}).waitFor();
   fail=false;rows=[];await page.getByRole('button',{name:'Retry',exact:true}).click();
   await page.getByText('No flagged plans in the available data.',{exact:true}).waitFor();
   rows=[swks,normal];await page.reload();await page.getByRole('heading',{name:'1 plan to review',exact:true}).waitFor();
   if(name==='desktop')assert(await page.getByRole('button',{name:'1 plan notice',exact:true}).isVisible());
   assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);await page.close();
   console.log(`PASS ${name} ${theme}: flags only, identities, explanations, cross-workspace safety, URL/reload, empty/error, no writes`);
  }
 }
} finally {await browser.close();await new Promise(r=>server.close(r));}
