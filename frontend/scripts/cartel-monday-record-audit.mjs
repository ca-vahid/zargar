// Static built UI + actual-shaped runtime DTO fixtures. Every API/WS request is synthetic.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, mkdir} from 'node:fs/promises';
import {resolve, extname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium, devices} from 'playwright';

const dist=fileURLToPath(new URL('../dist/',import.meta.url));
const output=fileURLToPath(new URL('../.mobile-shots/',import.meta.url));
await mkdir(output,{recursive:true});
const server=createServer(async(req,res)=>{
  const path=resolve(dist,new URL(req.url,'http://localhost').pathname.replace(/^\//,''));
  if(path!==resolve(dist) && !path.startsWith(resolve(dist)+'/') && !path.startsWith(resolve(dist)+'\\')) {res.writeHead(403).end();return;}
  try {res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.html':'text/html'})[extname(path)] || 'application/octet-stream');res.end(await readFile(path));}
  catch {res.setHeader('Content-Type','text/html');res.end(await readFile(resolve(dist,'index.html')));}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true});
const at=Date.parse('2026-09-14T13:30:00Z');
const plan=(id,policy)=>({runId:id,symbol:'TEST',mode:'plan',status:'done',verdict:'plan',
  createdAt:'2026-09-13T20:00:00Z',asOfMs:at-86400000,
  config:{preparation:{runId:'monday-prep',workspace:'practice',portfolioId:'practice'},inputs:{history:[]}},
  result:{plan:{plan:{id,symbol:'TEST',direction:'long',setup:'base',trigger:100,invalidation:95,targets:[110],
    first_session:'2026-09-14',last_session:'2026-09-14',entry:{timeframe_minutes:15,stop_mode:'session_extreme'}}},
    exitCampaign:{version:'cartel-exits-1',profile:'september_2026',allocation_policy:policy,
      rungs:[{id:'target1',kind:'target',target:110,fraction:.25},{id:'extension',kind:'extension',fraction:.25,ema_period:8,atr_multiple:3},
        {id:'ema8',kind:'ema',fraction:.2,ema_period:8},{id:'ema21',kind:'ema',fraction:.2,ema_period:21},{id:'ema50',kind:'ema',fraction:.1,ema_period:50}]}}});

try {
  for(const [device,options] of [['desktop',{viewport:{width:1440,height:1000}}],['phone',devices['iPhone 14']]]) {
    for(const workspace of ['practice','live']) {
      const page=await browser.newPage(options);
      page.setDefaultTimeout(15000);
      const errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message));
      const plans=[plan('monday-legacy','legacy'),plan('monday-v2','whole_contracts_v2'),plan('monday-filled','whole_contracts_v2')];
      const portfolio={id:'practice',name:'Cartel Practice',kind:'sim',currency:'USD',baseCurrency:'USD',cash:10000,equity:10000};
      // Matches runtime.detail: generic config, separate camelCase executionSettings and preparation.
      const arm={runId:'monday-legacy',symbol:'TEST',technique:'options_cartel',status:'armed',phase:'waiting',
        config:{mode:'auto',instrument:'options'},preparation:{runId:'monday-prep',workspace:'practice'},portfolio,
        executionSettings:{portfolioId:'practice',mode:'auto',instrument:'options',contractSymbol:'TEST261016C00100000',
          budget:500,riskPct:10,maxUnits:10,maxPremium:null,contractPolicy:null,overnightAck:true,allowLive:false},
        submissionReserved:false,trades:[],summary:'Cartel auto: waiting.',needsAttention:false};
      const filled={...arm,runId:'monday-filled',phase:'managed',trades:[{filledQty:3}],
        executionSettings:{...arm.executionSettings,contractPolicy:{maxAsk:5,maxSpreadPct:20}}};
      let replay=null;
      await page.routeWebSocket('**/ws**',socket=>socket.send(JSON.stringify({t:'snapshot',d:{
        settings:{'trading.mode':workspace,'techniques.options_cartel.default_portfolio':'practice'},portfolios:[portfolio],
        positions:[],openOrders:[],quotes:{},watchlists:[],proposals:[],halt:{halted:false},broker:{connected:true}}})));
      await page.route('**/api/**',async route=>{
        const request=route.request(),url=new URL(request.url());let data=[];
        if(request.method()==='POST') posts.push({path:url.pathname,body:request.postDataJSON()});
        if(url.pathname.startsWith('/api/auth/')) data={required:false,user:null};
        else if(url.pathname.endsWith('/armed/monday-legacy/review-limits')) {
          assert.equal(request.method(),'POST');assert.equal(workspace,'practice');
          arm.executionSettings.contractPolicy={maxAsk:5,maxSpreadPct:20};data=arm;
        } else if(url.pathname.endsWith('/runs/monday-v2/replay-campaign')) {
          const body=request.postDataJSON(),quantity=body.quantity ?? 2;
          replay={runId:'monday-replay',symbol:'TEST',mode:'replay',status:'done',verdict:'open',createdAt:new Date(at).toISOString(),asOfMs:at,
            result:{status:'open',dataComplete:true,quantity,quantityBasis:{kind:body.quantity==null?'current_funding_estimate':'hypothetical',
              note:body.quantity==null?'Current quote, premium budget and equity sizing; not historical funding or permission to trade.':'Explicit modeled units; account funding is not established.'},
              realizedR:0,openR:0,fills:[],pending:[]}};data=replay;
        } else if(url.pathname.endsWith('/runs/monday-prep')) data={runId:'monday-prep',result:{shortlist:plans.map(p=>({planId:p.runId,status:'armed'}))}};
        else if(url.pathname.endsWith('/runs/monday-replay')) data=replay;
        else if(plans.some(p=>url.pathname.endsWith(`/runs/${p.runId}`))) data=plans.find(p=>url.pathname.endsWith(`/runs/${p.runId}`));
        else if(url.pathname.endsWith('/runs')) data=['industry','fundamentals','membership'].includes(url.searchParams.get('mode'))?[]:[...plans,...(replay?[replay]:[])];
        else if(url.pathname.endsWith('/armed')) data=[arm,filled];
        else if(url.pathname.endsWith('/quote-recording')) data={enabled:false,errors:{},captured:0};
        else if(url.pathname.endsWith('/schedule')) data={configuration:{scanSymbols:[]},jobs:[]};
        else if(url.pathname.includes('/preparation')) data={configuration:{enabled:false},latest:null};
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
      });
      const open=async id=>{
        await page.goto(`${base}/techniques/options-cartel/run/${id}`);
        await page.locator('.splash').waitFor({state:'detached'});
        await page.getByRole('heading',{name:'TEST · plan',exact:true}).waitFor();
      };
      await open('monday-legacy');
      const reviewButton=page.getByRole('button',{name:'Review entry contract limits',exact:true});
      if(workspace==='practice') {
        await reviewButton.waitFor();assert(await reviewButton.isEnabled());
        await reviewButton.click();
        await page.getByText('Execution limits reviewed. Refresh the record to see the saved policy.',{exact:true}).waitFor();
        assert.equal(posts.filter(p=>p.path.endsWith('/review-limits')).length,1);
      } else assert.equal(await reviewButton.count(),0);
      await page.getByText('Whole-contract exit preview',{exact:true}).click();
      await page.getByLabel('Modeled exit contracts',{exact:true}).fill('2');
      assert(await page.getByText('extension: 1 contracts · 50.0% · unreachable without a first trim; held for final EMA or protection',{exact:true}).isVisible());
      await open('monday-v2');
      await page.getByText('Whole-contract exit preview',{exact:true}).click();
      const quantity=page.getByLabel('Modeled exit contracts',{exact:true});
      assert.equal(await quantity.inputValue(),'1');
      assert(await page.getByText(/One contract cannot be trimmed/).isVisible());
      for(const value of [2,3]) {
        await quantity.fill(String(value));
        assert(await page.getByText(`target1: 1 contracts · ${value===2?'50.0':'33.3'}%`,{exact:true}).isVisible());
        assert(await page.getByText(`ema50: 1 contracts · ${value===2?'50.0':'33.3'}% · requires first trim to fill`,{exact:true}).isVisible());
        assert(await page.getByText('extension: 0 contracts · 0.0% · skipped at this quantity',{exact:true}).isVisible());
      }
      assert(await page.getByText('ema8: 1 contracts · 33.3% · requires first trim to fill',{exact:true}).isVisible());
      await page.getByText('Replay this campaign',{exact:true}).click();
      const mode=page.getByRole('combobox',{name:'Replay quantity',exact:true});
      assert.equal(await mode.inputValue(),'observed');
      assert.equal(await page.getByLabel('Hypothetical units',{exact:true}).count(),0);
      await mode.selectOption('hypothetical');
      assert.equal(await page.getByLabel('Hypothetical units',{exact:true}).inputValue(),'1');
      await mode.selectOption('observed');
      await page.getByRole('button',{name:'Run campaign replay',exact:true}).click();
      await page.getByRole('region',{name:'Campaign replay result',exact:true}).waitFor();
      assert.equal(posts.find(p=>p.path.endsWith('/replay-campaign')).body.quantity,null);
      assert(await page.getByText(/^2 modeled units · Current quote/).isVisible());
      await open('monday-filled');
      await page.getByText('Whole-contract exit preview',{exact:true}).click();
      assert.equal(await page.getByLabel('Modeled exit contracts',{exact:true}).inputValue(),'3');
      assert(await page.getByText(/^Original confirmed filled quantity/).isVisible());
      assert.equal(await page.getByRole('button',{name:'Review entry contract limits',exact:true}).count(),0);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'record document overflow');
      await page.screenshot({path:resolve(output,`cartel-monday-record-${device}-${workspace}.png`),fullPage:true});
      assert(posts.every(p=>p.path.endsWith('/review-limits') || p.path.endsWith('/replay-campaign')),'unexpected action');
      assert.deepEqual(errors,[]);
      console.log(`PASS ${device} ${workspace}: actual DTO, bounded legacy review, reachable 1/2/3 lots, automatic replay sizing, no overflow`);
      await page.close();
    }
  }
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
