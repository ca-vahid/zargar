// Isolated built-UI audit. Every API/WS response is synthetic; no engine or DB.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, mkdir} from 'node:fs/promises';
import {extname, resolve, sep} from 'node:path';
import {chromium, devices} from 'playwright';

const dist = resolve('dist');
await mkdir('.mobile-shots', {recursive:true});
const server = createServer(async (request,response) => {
  const pathname = new URL(request.url,'http://localhost').pathname.replace(/^\//,'');
  const file = resolve(dist,pathname);
  if (file !== dist && !file.startsWith(dist+sep)) {response.writeHead(403).end(); return;}
  try {
    response.setHeader('Content-Type', ({'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[extname(file)] || 'text/html');
    response.end(await readFile(file));
  } catch {
    response.setHeader('Content-Type','text/html'); response.end(await readFile(resolve(dist,'index.html')));
  }
});
await new Promise(done => server.listen(0,'127.0.0.1',done));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({headless:true});
const at = Date.parse('2026-09-15T16:00:00Z');
const candidates = Array.from({length:50},(_,index) => ({
  baselineAttempts:2, entryPolicyStudy:index===0?{rows:[{variant:'gap_retest_v1',status:'waiting',prospectiveConfirmation:false},{variant:'volume_1x_v1',status:'waiting',prospectiveConfirmation:false}]}:null,
  id:`candidate-${index}`, symbol:index===0?'BOX':index===24?'GH':`TEST${index}`,
  direction:index<25?'long':'short', cohort:index<25?'primary':'bearish', baselineRank:index%25+1,
  leaderRank:25-index%25, status:index===0?'hypothetical_stock_confirmation':'waiting',
  reasons:index===0?['Recorded stock confirmation; option eligibility has not been established.']:[],
  entry:index===0?{at,referencePrice:35.24,stop:34.45,risk:.79}:null,
  experiments:index===0?{version:'campaign-v1',status:'observed',entry:{at,signalAt:at-60000,price:35.24,stop:34.45,quantity:2,quantityBasis:'explicit hypothetical quantity',instrument:'underlying_proxy'},
    targetDiagnostic:{originalTargets:[36.05],nearestTarget:{price:36.05,rewardR:1.02,passes:true},firstExecutableExit:{id:'target1',kind:'target',quantity:1,price:36.05},campaignTarget:{price:36.05,rewardR:1.02,passes:true,reason:'Nearest resistance remains recorded.'}},
    variants:[{id:'baseline_v1',label:'Baseline campaign',status:'open',dataComplete:true,firstExit:null,remainingQty:2,grossUnderlyingPnl:-.85,netUnderlyingPnl:null,fees:null,optionValuation:null,warnings:['Complete transaction costs are unavailable.']},
      {id:'failed_break_v1',label:'Failed breakout',status:'closed',dataComplete:false,firstExit:{at:at+900000,price:35.05,kind:'failed_break',qty:2},remainingQty:0,grossUnderlyingPnl:-.38,netUnderlyingPnl:null,fees:null,optionValuation:null,warnings:['Sampled bar is not a source-qualified exit.']}],warnings:[],placesOrders:false}:null,
  gaps:index===0?['option_quotes_missing','costs_missing']:[],
}));
candidates[1].experiments={version:'campaign-v1',status:'observed',entry:{at,price:35.24,stop:34.45,quantity:1,quantityBasis:'current_funding_estimate',instrument:'underlying_proxy'},
  targetDiagnostic:{originalTargets:[36.05],nearestTarget:{price:36.05,rewardR:1.02,passes:true},firstExecutableExit:{id:'ema50',kind:'ema',quantity:1,price:null},campaignTarget:{price:null,rewardR:null,passes:null,reason:'One unit has no fixed-price strength trim.'}},
  variants:[],warnings:['One unit cannot make a partial strength trim; baseline retained.'],placesOrders:false};
candidates[2].experiments={version:'campaign-v1',status:'quantity_unknown',entry:{at,price:35.24,stop:34.45,quantity:null,quantityBasis:'unknown',instrument:'underlying_proxy'},
  variants:[],warnings:['No eligible contract quantity was established.'],placesOrders:false};
candidates[0].entryComparison={baseline:{status:'triggered',signal:{at}},campaignAware:{status:'triggered',comparisonTarget:36.05},originalTargets:[36.05]};
candidates[0].optionObservation={status:'observed',observedAt:at,selected:{symbol:'BOX261016C00035000'},timely:true,
  funding:{quantity:2,cashCapUsd:500},quote:{status:'observed',bid:1.9,ask:2,source:'opra',sourceAt:at-500},selectionErrors:[]};
candidates[3].targetRoomProbe={at,referencePrice:53.7,stop:52.9};
candidates[3].entryComparison={baseline:{status:'waiting'},campaignAware:{status:'target_unknown',comparisonTarget:null,reason:'Quantity is unknown; no static target permission inferred.'},originalTargets:[53.81]};
candidates[4].sharesComparison={status:'evaluated',reason:'Affordability-only scenario.',skip:{cashBudget:500,netPnl:0,investedCash:0},
  shares:{quantity:10,cashBudget:500,investedCash:352.4,idleCash:147.6,leverage:1,initialStopRisk:7.9,study:{
    ...candidates[0].experiments,entry:{at,price:35.24,stop:34.45,quantity:10,quantityBasis:'equal_cash_unlevered_shares',instrument:'shares'},
    variants:[{id:'baseline_v1',label:'Saved share campaign',status:'open',dataComplete:true,firstExit:null,remainingQty:10,grossUnderlyingPnl:-4.25,netUnderlyingPnl:-4.45,fees:.2,optionValuation:null,warnings:[]}],
  }}};
candidates[5].campaignExperiments={...candidates[0].experiments,status:'evaluated'};

function report(day,enabled=true,empty=false) {
  return {day,workspace:'practice',researchOnly:true,placesOrders:false,enabled,status:empty?'awaiting_preparation':'observing',asOfMs:empty?null:at,
    denominator:{discovered:3072,evaluated:3070,eligible:empty?0:64,observed:empty?0:50,boundedLimit:50,omitted:empty?0:14,primaryEligible:empty?0:32,bearishEligible:empty?0:32,baselineReady:empty?0:30},
    candidates:empty?[]:candidates,rankings:empty?{}:{primary:{baselineIds:['candidate-0','candidate-1'],leaderIds:['candidate-24','candidate-23'],overlapIds:[],candidates:candidates.filter(c=>c.cohort==='primary').map(({id,symbol})=>({id,symbol}))},bearish:{baselineIds:['candidate-25','candidate-26'],leaderIds:['candidate-49','candidate-48'],overlapIds:[],candidates:candidates.filter(c=>c.cohort==='bearish').map(({id,symbol})=>({id,symbol}))}},
    bearish:{status:empty?'awaiting_context':'observing',eligible:empty?0:32,observed:empty?0:25,rows:empty?[]:candidates.slice(25)},
    experiments:[{id:'baseline_v1',label:'Saved exit campaign',rule:'Original campaign and protective stop.'},
      {id:'failed_break_v1',label:'Confirmed failed break',rule:'Exit at the next expected minute open after a source-qualified close back through the original trigger.'},
      {id:'time_60m_v1',label:'60-minute holding cap',rule:'Exit after 60 completed regular-session minutes; next expected minute open.'},
      {id:'weak_strength_v1',label:'Weak-environment strength trim',rule:'With weak context known by entry, trim half of whole units at +0.5 initial R. One unit cannot trim.'}],
    gaps:empty?[]:[{kind:'option_quotes_missing',count:50,reason:'No contemporaneous option quote sequence.'},{kind:'costs_missing',count:50,reason:'Net option outcomes are not priced.'}],
    protocol:{version:'profitability-lab-v1'}};
}

async function setup(options={},workspace='practice',theme='dark') {
  const page = await browser.newPage({...options,locale:'en-US',timezoneId:'America/New_York'});
  const errors=[],writes=[],reads=[];
  let enabled=true,failNext=false,holdNext=false,release;
  page.on('pageerror',error => errors.push(error.message));
  await page.routeWebSocket('**/ws**',socket => socket.send(JSON.stringify({t:'snapshot',d:{
    settings:{'trading.mode':workspace,'ui.theme':theme},portfolios:[],positions:[],quotes:{},watchlists:[],openOrders:[],proposals:[],halt:{engaged:false,books:{}},broker:{mode:workspace,feedConnected:true},
  }})));
  await page.route('**/api/**',async route => {
    const request=route.request(),url=new URL(request.url()); let data=[];
    if (request.method()!=='GET') writes.push({path:url.pathname,body:request.postDataJSON()});
    if (url.pathname.startsWith('/api/auth/')) data={required:false,user:null};
    else if (url.pathname==='/api/settings' && request.method()==='PATCH') {
      enabled=request.postDataJSON()['techniques.options_cartel.profitability_research']; data=request.postDataJSON();
    } else if (url.pathname==='/api/options-cartel/preparation') data={configuration:{enabled:false,workspace,portfolioId:'',budget:500,riskPct:10,
      profile:'september_2026',entry:{timeframe_minutes:15,mode:'breakout',volume_multiple:1.5,min_close_location:.7},
      exitProfile:'september_2026',horizonSessions:1,septemberFractions:[.25,.25,.2,.2,.1],allowFibonacciTargets:true},latest:null};
    else if (url.pathname==='/api/options-cartel/intraday-research') data={enabled:false,rows:[],placesOrders:false};
    else if (url.pathname==='/api/options-cartel/schedule') data={configuration:{scanSymbols:[],scanEnabled:false,scanProfile:'september_2026',scanDirection:'long',recoveryEnabled:false},jobs:[]};
    else if (url.pathname==='/api/options-cartel/quote-recording') data={enabled:false,running:false,lastAttemptAt:null,captured:0,errors:{}};
    else if (url.pathname==='/api/options-cartel/profitability-research') {
      reads.push(url.searchParams.toString());
      assert.equal(url.searchParams.get('workspace'),'practice');
      if (holdNext) {holdNext=false; await new Promise(done => {release=done;});}
      if (failNext) {failNext=false; await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Research snapshot temporarily unavailable.'})}); return;}
      data=report(url.searchParams.get('day'),enabled,url.searchParams.get('day')==='2026-09-01');
    }
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  return {page,errors,writes,reads,fail:()=>{failNext=true;},hold:()=>{holdNext=true;},release:()=>release?.()};
}

async function ready(page,route='/techniques/options-cartel/validation') {
  await page.goto(base+route); await page.locator('.splash').waitFor({state:'detached'});
  return page.getByRole('region',{name:route.endsWith('settings')?'Profitability research settings':'Profitability research',exact:true});
}
async function layout(page,panel) {
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'document must not overflow');
  if (page.viewportSize().width < 768) assert.equal(await panel.locator('input,select').evaluateAll(elements=>elements.filter(e=>parseFloat(getComputedStyle(e).fontSize)<16).length),0,'inputs must not zoom on mobile');
}

try {
  for (const [device,options] of [['desktop',{viewport:{width:1440,height:1100}}],['phone',devices['iPhone SE']]]) {
    for (const theme of ['light','dark']) {
      const fixture=await setup(options,'practice',theme),{page}=fixture;
      const panel=await ready(page); await panel.getByText('3,070 / 3,072',{exact:true}).waitFor();
      await panel.getByRole('combobox',{name:'Research ranking order'}).selectOption('leaderRank');
      assert.equal(await panel.locator('.cartel-research-table > tbody > tr').first().locator('td strong').first().innerText(),'GH');
      await panel.getByRole('combobox',{name:'Research candidate cohort'}).selectOption('bearish');
      assert.equal(await panel.getByText('BOX',{exact:true}).count(),0);
      await panel.getByRole('combobox',{name:'Research candidate cohort'}).selectOption('all');
      await panel.getByRole('combobox',{name:'Research ranking order'}).selectOption('baselineRank');
      await panel.getByRole('button',{name:'Show all observed candidates'}).click();
      assert.equal(await panel.locator('.cartel-research-table > tbody > tr').count(),50);
      await panel.getByText('Study evidence for BOX',{exact:true}).click();
      await panel.getByText('Controlled entry-policy study',{exact:true}).click();
      await panel.getByText('gap retest v1',{exact:true}).waitFor();
      await panel.getByText('Estimated whole contracts: 2',{exact:false}).waitFor();
      await panel.getByText('Recorded quote: observed',{exact:false}).waitFor();
      await panel.getByText('Net: Not priced; complete costs required',{exact:true}).first().waitFor();
      await panel.getByText('Gross: -0.85 proxy units',{exact:false}).filter({visible:true}).waitFor();
      assert.equal(await panel.getByText('Option outcome not priced.',{exact:true}).filter({visible:true}).count(),2);
      await panel.getByText('Study evidence for TEST1',{exact:true}).click();
      await panel.getByText('One unit has no fixed-price strength trim.',{exact:false}).waitFor();
      await panel.getByText('Study evidence for TEST2',{exact:true}).click();
      await panel.getByText('No eligible contract quantity was established.',{exact:true}).waitFor();
      await panel.getByText('Study evidence for TEST3',{exact:true}).click();
      await panel.getByText('This probe retains the target veto; it is not an eligible baseline entry.',{exact:false}).waitFor();
      await panel.getByText('Study evidence for TEST4',{exact:true}).click();
      await panel.getByText('Ordinary shares versus cash',{exact:true}).click();
      await panel.getByText('Net: $-4.45 share scenario',{exact:true}).waitFor();
      await panel.getByText('Study evidence for TEST5',{exact:true}).click();
      await panel.getByText('Campaign-target challenger outcomes',{exact:true}).click();
      await panel.getByText('Policy comparisons and evidence limits',{exact:true}).click();
      await panel.getByText('Failed-break containment',{exact:true}).waitFor();
      await panel.getByText('60-minute holding cap',{exact:true}).waitFor();
      await panel.getByText('Compare the two ranked shortlists',{exact:true}).click();
      await panel.getByText('Leader-first list: GH, TEST23',{exact:true}).waitFor();
      await layout(page,panel); await panel.getByRole('heading',{name:'Profitability research',exact:true}).scrollIntoViewIfNeeded();
      await page.screenshot({path:`.mobile-shots/cartel-profitability-${device}-${theme}.png`});
      await panel.getByLabel('Profitability research session').fill('2026-09-01');
      await panel.getByText('No preparation recorded for this session',{exact:true}).waitFor();
      assert.equal(await panel.getByText('BOX',{exact:true}).count(),0);
      assert.deepEqual(fixture.errors,[]); assert.deepEqual(fixture.writes,[]);
      await page.close(); console.log(`PASS ${device} ${theme}: denominator, rankings, bearish filter, full pool, economics gaps, date reset, layout, no writes`);
    }
  }
  for (const route of ['/techniques/options-cartel/validation','/techniques/options-cartel/settings']) {
    const fixture=await setup({},'live'),panel=await ready(fixture.page,route);
    await panel.getByText(/Available in Practice only/).waitFor();
    assert.equal(await panel.locator('input,select,button').count(),0);
    assert.deepEqual(fixture.reads,[]); assert.deepEqual(fixture.writes,[]); assert.deepEqual(fixture.errors,[]);
    await fixture.page.close(); console.log(`PASS Live ${route}: no collection/data controls or requests`);
  }
  {
    const fixture=await setup(),panel=await ready(fixture.page,'/techniques/options-cartel/settings');
    const toggle=panel.getByRole('checkbox',{name:'Collect profitability research in Practice'});
    await toggle.waitFor(); assert(await toggle.isChecked());
    await toggle.uncheck(); await panel.getByRole('button',{name:'Save research collection'}).click();
    await panel.getByText('Research collection setting saved.',{exact:true}).waitFor();
    assert.deepEqual(fixture.writes,[{path:'/api/settings',body:{'techniques.options_cartel.profitability_research':false}}]);
    assert.deepEqual(fixture.errors,[]); await fixture.page.close(); console.log('PASS Settings: only the namespaced collection toggle changes');
  }
  {
    const fixture=await setup(); fixture.fail(); const panel=await ready(fixture.page);
    await panel.getByRole('alert').filter({hasText:'Research snapshot temporarily unavailable.'}).waitFor();
    await panel.getByRole('button',{name:'retry',exact:true}).click();
    await panel.getByText('BOX',{exact:true}).waitFor();
    fixture.hold(); await panel.getByLabel('Profitability research session').fill('2026-09-02');
    await panel.getByRole('status',{name:'Loading profitability research…'}).waitFor();
    assert.equal(await panel.getByText('BOX',{exact:true}).count(),0);
    await panel.getByLabel('Profitability research session').fill('2026-09-01');
    await panel.getByText('No preparation recorded for this session',{exact:true}).waitFor();
    const staleResponse=fixture.page.waitForResponse(response=>response.url().includes('day=2026-09-02'));
    fixture.release();
    await staleResponse;
    assert.equal(await panel.getByText('BOX',{exact:true}).count(),0);
    assert.deepEqual(fixture.errors,[]); assert.deepEqual(fixture.writes,[]);
    await fixture.page.close(); console.log('PASS Loading/error/retry and stale date-response exclusion');
  }
} finally {
  await browser.close(); await new Promise(done => server.close(done));
}
