'use strict';
// Check overview visibility using backend status fixtures, without a host/browser.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const nodes=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',textContent:'',addEventListener(){}});return nodes.get(selector);};
let clockPresent=false,clockNow=new Date('2026-10-01T23:59:00').getTime(),timerId=0,requests=0;
const listeners={},timers=new Map();
class ClockDate extends Date {constructor(...args){super(...(args.length?args:[clockNow]));}static now(){return clockNow;}}
const document={hidden:false,querySelector:selector=>selector.startsWith('#dashboard-')&&!clockPresent?null:node(selector),querySelectorAll:()=>[],addEventListener:(name,callback)=>listeners[name]=callback};
const context=vm.createContext({document,window:{addEventListener:(name,callback)=>listeners[name]=callback},location:{hash:'#dashboard'},Date:ClockDate,setTimeout:()=>0,setInterval:(callback,delay)=>{const id=++timerId;timers.set(id,{callback,delay});return id;},clearInterval:id=>timers.delete(id),console});
const source=fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,'');
vm.runInContext(source,context);
const evaluate=expression=>vm.runInContext(expression,context);
const active={installed:true,active:true,state:'active',configured:true,relevant:true};
const missing={installed:false,active:false,state:'not-installed',configured:false,relevant:false};
const status={hostname:'test-nas',uptime:10,load:0,cpus:2,memory_used:100,memory_total:1000,
 storage:{used:100,total:1000},services:{},service_details:{web:{...active},agent:{...active},https:{...active},
 docker:{...missing},samba:{...missing},vms:{...missing},zfs:{...missing,installed:true,state:'unused'}}};
context.fetch=async url=>{requests++;return {ok:true,json:async()=>url==='/api/status'?status:url==='/api/apps'?{installed:[]}:url==='/api/shares'?[]:{vms:[]}};};
evaluate("session={user:{name:'admin',role:'admin'}};");
(async()=>{
 const health=html=>html.split(/<h2[^>]*>Systemstatus<\/h2>/)[1].split('</section>')[0];
 let html=health(await evaluate('pages.dashboard()'));
 assert(html.includes('Titan-Oberfläche'));
 assert(html.includes('Titan-Verwaltung'));
 assert(html.includes('HTTPS'));
 for(const label of ['Docker','SMB-Freigaben','ZFS-Speicher','Virtualisierung'])assert(!html.includes(label));
 assert.equal(node('#footer-state').textContent,'Alle eingerichteten Dienste aktiv');
 // Configured workloads keep absent or failed components visible for diagnosis.
 status.service_details.docker={...missing,configured:true,relevant:true};
 status.service_details.vms={...active,active:false,state:'failed'};
 html=health(await evaluate('pages.dashboard()'));
 assert(html.includes('Docker'));
 assert(html.includes('Nicht installiert'));
 assert(html.includes('Virtualisierung'));
 assert(html.includes('Fehlgeschlagen'));
 assert.equal(node('#footer-state').textContent,'Dienste prüfen');
 // Installed legacy backends without relevance metadata still render.
 status.service_details={docker:{installed:true,active:true,state:'active'}};
 html=health(await evaluate('pages.dashboard()'));
 assert(html.includes('Docker'));
 assert(!html.includes('ZFS-Speicher'));
 // The clock updates only its text nodes, including the midnight date change.
 assert(evaluate('dashboardDateCard()').includes('id="dashboard-time"'));
 assert(evaluate('dashboardDateCard()').includes('id="dashboard-date"'));
 clockPresent=true;
 node('#main').innerHTML='untouched-dashboard';
 node('#dialog-body').innerHTML='untouched-form';
 const requestsBefore=requests;
 evaluate('syncDashboardClock()');
 assert.equal(timers.size,1);
 assert.equal(node('#dashboard-time').textContent,'23:59');
 assert.match(node('#dashboard-date').textContent,/1\. Oktober/);
 const timer=[...timers.values()][0];
 assert.equal(timer.delay,1000);
 clockNow+=60000;
 timer.callback();
 assert.equal(node('#dashboard-time').textContent,'00:00');
 assert.match(node('#dashboard-date').textContent,/2\. Oktober/);
 assert.equal(node('#main').innerHTML,'untouched-dashboard');
 assert.equal(node('#dialog-body').innerHTML,'untouched-form');
 assert.equal(requests,requestsBefore);
 // Hidden tabs stop polling; returning immediately catches up without duplicates.
 document.hidden=true;
 listeners.visibilitychange();
 assert.equal(timers.size,0);
 clockNow+=5*3600000;
 document.hidden=false;
 listeners.visibilitychange();
 assert.equal(node('#dashboard-time').textContent,'05:00');
 assert.equal(timers.size,1);
 listeners.pageshow();
 assert.equal(timers.size,1);
 evaluate("page='files';syncDashboardClock()");
 assert.equal(timers.size,0);
 evaluate("page='dashboard';session.user=null;syncDashboardClock()");
 assert.equal(timers.size,0);
 const rows=evaluate("jobRows([{id:'safe',username:'<user>',action:'app_install',time:1,status:'failed',result:{error:'<script>bad</script>'}}])");
 assert(rows.includes('App installieren'));assert(rows.includes('Fehlgeschlagen'));assert(rows.includes('&lt;script&gt;'));assert(!rows.includes('<script>'));
 assert(!evaluate("nav.some(([key])=>key==='jobs')"));
 console.log('Web status: relevant services and configured failures; live clock, midnight, hidden tabs and isolated forms passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
