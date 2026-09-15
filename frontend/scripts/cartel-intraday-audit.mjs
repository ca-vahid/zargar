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

const observation={id:'research-one',at:Date.now(),market:{status:'sustained_improvement',sustained:true,indices:{SPY:{status:'observed',close:101,dailyEmas:{'8':100,'21':99,'50':98}},QQQ:{status:'observed',close:101,dailyEmas:{'8':100,'21':99,'50':98}}}},candidates:[{symbol:'TEST',status:'hypothetical_stock_confirmation',signal:{at:Date.now()}}]};
try{
 for(const [device,options] of [['desktop',{viewport:{width:1440,height:1000}}],['phone',devices['iPhone SE']]]){
  for(const workspace of ['practice','live']){
   const page=await browser.newPage(options),errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
   await page.routeWebSocket('**/ws**',socket=>socket.send(JSON.stringify({t:'snapshot',d:{settings:{'trading.mode':workspace},portfolios:[],positions:[],quotes:{},watchlists:[],openOrders:[],proposals:[],halt:{engaged:false,books:{}},broker:{mode:workspace,feedConnected:true}}})));
   await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url());let data=[];
    if(route.request().method()!=='GET')writes.push(url.pathname);
    if(url.pathname.startsWith('/api/auth/'))data={required:false,user:null};
    else if(url.pathname==='/api/options-cartel/preparation')data={configuration:{enabled:false,workspace,portfolioId:'',budget:500,riskPct:10},latest:null};
    else if(url.pathname==='/api/options-cartel/intraday-research')data={enabled:workspace==='practice',rows:workspace==='practice'?[observation]:[],placesOrders:false};
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
   });
   await page.goto(base+'/techniques/options-cartel');await page.locator('.splash').waitFor({state:'detached'});
   const panel=page.getByRole('region',{name:'Intraday market research',exact:true});await panel.scrollIntoViewIfNeeded();
   if(workspace==='practice')await panel.getByText(/hypothetical stock confirmation/).first().waitFor();
   else {await panel.getByText('Available in Practice only. Live permissions are unchanged.',{exact:true}).waitFor();assert.equal(await panel.getByText('TEST',{exact:true}).count(),0);}
   assert.equal(await panel.getByRole('button',{name:/arm|approve|execute/i}).count(),0);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.screenshot({path:`.mobile-shots/intraday-${device}-${workspace}.png`});
   assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);await page.close();
   console.log(`PASS ${device} ${workspace}: research labels, no execution controls, scope, no writes`);
  }
 }
}finally{await browser.close();await new Promise(r=>server.close(r));}
