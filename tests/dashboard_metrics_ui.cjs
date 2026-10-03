'use strict';
// Verify real metric semantics, missing samples, escaping and polling lifecycle.
const assert = require('node:assert/strict');
const dashboard = require('../titan/web/dashboard.js');
const turns = () => new Promise(resolve => setImmediate(resolve));

const status = {cpu_percent:0,load:12,cpus:4,memory_total:1000,memory_used:250,uptime:3601,
 cpu_temperature:null,temperatures:[],telemetry_sampled_at:1700000000,status_history:[]};
assert.equal(dashboard.metricValues(status).cpu,0,'zero CPU activity is a real measurement');
assert.equal(dashboard.metricValues({...status,cpu_percent:null}).cpu,null,'load average cannot fill in CPU utilization');
assert.equal(dashboard.metricValues({...status,memory_total:0}).memory,null,'absent RAM is not zero percent used');
assert.equal(dashboard.metricValues({...status,memory_used:1001}).memory,null);
assert.equal(dashboard.metricValues({...status,cpu_percent:101}).cpu,null);
assert.equal(dashboard.metricValues({...status,cpu_percent:'20'}).cpu,null);
assert.equal(dashboard.metricValues(status).memory,25);
assert.equal(dashboard.metricValues({...status,memory_occupied:900}).memory,90);
assert.equal(dashboard.historySamples([{time:10,memory_percent:25,memory_occupied_percent:90}])[0].memory_percent,90);
const occupied=dashboard.resourceMetrics({...status,memory_occupied:900,memory_free:100,memory_available:750});
assert(occupied.includes('inklusive Cache'));assert(occupied.includes('Bedarf (geschätzt)'));assert(!occupied.includes('Proxmox'));
const html = dashboard.resourceMetrics(status);
assert(html.includes('CPU-Auslastung'));
assert(html.includes('aria-valuenow="0.0"'));
assert(html.includes('aria-valuenow="25.0"'));
assert(html.includes('Kein CPU-Sensor'));
assert(html.includes('Der Verlauf baut sich mit den Messungen auf.'));
const unavailable = dashboard.resourceMetrics({...status,cpu_percent:null,memory_total:null,memory_used:null});
assert(unavailable.includes('Messung läuft'));
assert(!unavailable.includes('aria-valuenow='));
const unsafe = dashboard.resourceMetrics({...status,cpu_temperature:45,temperatures:[{label:'<img src=x onerror=bad()>',current:45}],telemetry_errors:{cpu:'<script>bad()</script>'}});
assert(!unsafe.includes('<img src=x'));
assert(!unsafe.includes('<script>bad()'));
assert(unsafe.includes('&lt;img src=x'));
assert(unsafe.includes('&lt;script&gt;'));

const samples = [
 {time:1000,cpu_percent:10,memory_percent:25},
 {time:1005,cpu_percent:null,memory_percent:26},
 {time:1010,cpu_percent:30,memory_percent:27},
 {time:1015,cpu_percent:40,memory_percent:28},
];
const graph = dashboard.metricChart(samples);
assert(graph.includes('4 Messpunkte'));
assert(graph.includes('Fehlende Messungen bleiben Lücken'));
assert.match(graph,/<circle class="chart-cpu"/,'the isolated first CPU sample is not connected across a missing sample');
assert.equal((graph.match(/<path class="chart-cpu"/g)||[]).length,1);
assert(!graph.includes('NaN'));
assert(!graph.includes('Infinity'));
assert(dashboard.metricChart(samples,{demo:true}).includes('Demo · Beispielverlauf'));
assert(!dashboard.metricChart(samples,{demo:true}).includes('Echte Messungen'));
assert(dashboard.resourceMetrics({...status,status_history:samples},{demo:true}).includes('Demo · Beispielverlauf'));
assert.equal(dashboard.historySamples([{time:1010,cpu_percent:50},{time:1000,cpu_percent:5},{time:1010,cpu_percent:60},{time:'1001',cpu_percent:6}]).length,2);
assert.equal(dashboard.historySamples([{time:1010,cpu_percent:50},{time:1010,cpu_percent:60}])[0].cpu_percent,60);
assert.equal(dashboard.historySamples(Array.from({length:200},(_,index)=>({time:1000+index,cpu_percent:5}))).length,180);

class Element {
 constructor(id,attributes={}){this.id=id;this.dataset=attributes;this.events=new Map();this.style={};this.hidden=false;this.disabled=false;this.textContent='';this.innerHTML='';this.classList={toggle(){},add(){},remove(){}};}
 addEventListener(name,callback){this.events.set(name,callback);}
 removeEventListener(name,callback){if(this.events.get(name)===callback)this.events.delete(name);}
 querySelector(selector){return this.nodes?.[selector]||null;}
 querySelectorAll(selector){return this.lists?.[selector]||[];}
 focus(){}
 dispatch(name,target){this.events.get(name)?.({target});}
}
function fixture(){
 let interval,cleared=false;
 const doc=new Element('document');doc.hidden=false;
 doc.defaultView={setInterval(callback,ms){assert.equal(ms,10000);interval=callback;return 42;},clearInterval(id){assert.equal(id,42);cleared=true;}};
 const grid=new Element('grid');grid.ownerDocument=doc;
 const main=new Element('main'),live=new Element('live'),updated=new Element('updated');
 live.nodes={'[data-metrics-updated]':updated};live.lists={'[data-percent]':[]};
 main.nodes={'#dashboard-grid':grid,'[data-live-resources]':live,'#dashboard-layout-hint':new Element('hint'),'#dashboard-layout-announcement':new Element('announcement')};
 for(const attr of ['data-layout-edit','data-layout-reset','data-layout-cancel','data-layout-save'])main.nodes[`[${attr}]`]=new Element(attr);
 const tiles=dashboard.ids.map(id=>{const tile=new Element(id,{dashboardTile:id});tile.nodes={'h2':new Element('title'),'[data-layout-move="-1"]':new Element('back'),'[data-layout-move="1"]':new Element('forward'),'[data-layout-handle]':new Element('handle')};return tile;});
 grid.lists={'[data-dashboard-tile]':tiles,'.tile-controls':[]};grid.nodes={'[data-layout-handle]':tiles[0].nodes['[data-layout-handle]']};
 for(const attr of ['data-layout-edit','data-layout-cancel'])main.nodes[`[${attr}]`].closest=selector=>selector===`[${attr}]`?main.nodes[selector]:null;
 return {doc,main,live,updated,poll:()=>interval(),cleared:()=>cleared};
}
(async()=>{
 const view=fixture();let requests=0,resolve;
 const api=async()=>{requests++;return status;};
 dashboard.mount(view.main,{api,owner:'admin',toast(){}});
 await view.poll();assert.equal(requests,1);assert(view.live.innerHTML.includes('CPU-Auslastung'));
 view.doc.hidden=true;await view.poll();assert.equal(requests,1,'hidden tab does not poll');
 view.doc.hidden=false;view.doc.dispatch('visibilitychange');await turns();assert.equal(requests,2);
 view.main.dispatch('click',view.main.nodes['[data-layout-edit]']);await view.poll();assert.equal(requests,2,'tile arrangement remains stable while editing');
 dashboard.dispose();assert(view.cleared());assert(!view.doc.events.has('visibilitychange'));
 const stale=fixture();
 dashboard.mount(stale.main,{api:()=>new Promise(done=>resolve=done),owner:'admin',toast(){}});
 const pending=stale.poll();dashboard.dispose();resolve(status);await pending;
 assert.equal(stale.live.innerHTML,'','late response cannot render a page that has been left');
 const failed=fixture();dashboard.mount(failed.main,{api:async()=>{throw Error('offline');},owner:'admin',toast(){}});
 await failed.poll();assert.equal(failed.updated.textContent,'Verbindung unterbrochen');dashboard.dispose();
 console.log('Dashboard metrics: CPU/load distinction, zero/null semantics, RAM validity, chart gaps, escaping, foreground polling, edit pause and disposal passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
