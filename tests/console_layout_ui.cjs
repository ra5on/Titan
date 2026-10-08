'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('titan/web/console.js','utf8').replace("import('/novnc/core/rfb.js')",'loadRFB()');
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const storage=new Map();
function fixture(id='vm-one',blockedStorage=false){
 const nodes=new Map(),timers=new Map(),events=new Map(),docEvents=new Map(),clients=[];let clock=0,next=0,options,observer;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',handlers:new Map(),addEventListener(k,f){this.handlers.set(k,f);}});return nodes.get(id);};
 class RFB{constructor(){this.events=new Map();this.scales=[];clients.push(this);}set scaleViewport(v){this.scale=v;this.scales.push(v);}get scaleViewport(){return this.scale;}addEventListener(k,f){this.events.set(k,f);}emit(k){this.events.get(k)?.();}sendKey(){}focus(){}disconnect(){this.emit('disconnect');}}
 const win={TitanVMConsole:{mount:opts=>{options=opts;return {update(){},destroy(){}};}},localStorage:{getItem:k=>{if(blockedStorage)throw Error('denied');return storage.get(k);},setItem:(k,v)=>{if(blockedStorage)throw Error('denied');storage.set(k,v);}},ResizeObserver:class{constructor(fn){this.fn=fn;observer=this;}observe(n){this.node=n;}disconnect(){this.disconnected=true;}},addEventListener:(k,f)=>events.set(k,f),removeEventListener:k=>events.delete(k)};
 const ctx={URLSearchParams,location:{search:'?vm='+id,protocol:'http:',host:'localhost'},document:{body:{dataset:{}},querySelector:node,addEventListener:(k,f)=>docEvents.set(k,f),removeEventListener:k=>docEvents.delete(k)},window:win,fetch:async()=>({ok:true,json:async()=>({ready:true})}),loadRFB:async()=>({default:RFB}),setTimeout:(fn,delay)=>{const key=++next;timers.set(key,{fn,at:clock+delay});return key;},clearTimeout:key=>timers.delete(key)};
 vm.runInNewContext(source,ctx);
 return {clients,timers,events,docEvents,node,get options(){return options;},get observer(){return observer;},advance(ms){clock+=ms;for(const [key,t]of [...timers])if(t.at<=clock){timers.delete(key);t.fn();}}};
}
(async()=>{
 const f=fixture();await flush();const client=f.clients[0];assert.equal(client.resizeSession,false);client.emit('connect');assert.equal(f.options.displayMode(),'fixed');f.advance(350);assert.equal(client.resizeSession,false,'Unknown/text guests never receive a guest resolution change');
 f.options.setDisplayMode('graphical');assert.equal(client.resizeSession,false);f.advance(349);assert.equal(client.resizeSession,false);f.advance(1);assert.equal(client.resizeSession,true);
 const count=client.scales.length;f.observer.fn();f.advance(200);f.events.get('resize')();f.advance(349);assert.equal(client.scales.length,count,'Resize bursts wait for the final settled layout');f.advance(1);assert.equal(client.scales.length,count+1);assert.equal(client.resizeSession,true);
 client.scaleViewport=false;f.docEvents.get('fullscreenchange')();f.advance(350);assert.equal(client.scaleViewport,false,'Fullscreen must preserve an explicit 1:1 view');
 const reopened=fixture();await flush();const second=reopened.clients[0];second.emit('connect');assert.equal(reopened.options.displayMode(),'graphical');assert.equal(second.resizeSession,false);reopened.advance(350);assert.equal(second.resizeSession,true,'Guest profile survives reopen for the same VM');
 const other=fixture('vm-two');await flush();assert.equal(other.options.displayMode(),'fixed','Guest profiles do not leak between VMs');
 f.options.setDisplayMode('fixed');f.advance(350);assert.equal(client.resizeSession,false);assert.equal(storage.get('titan.vm.console.display.v1:vm-one'),'fixed');
 f.events.get('resize')();const stale=[...f.timers.values()].at(-1).fn;client.emit('disconnect');stale();assert.equal(client.resizeSession,false,'A disconnected client cannot be resized by a stale callback');
 f.events.get('pagehide')();assert.equal(f.timers.size,0);assert(f.observer.disconnected);assert(!f.events.has('resize'));assert(!f.docEvents.has('fullscreenchange'));
 const denied=fixture('vm-denied',true);await flush();denied.clients[0].emit('connect');denied.options.setDisplayMode('graphical');denied.advance(350);assert.equal(denied.clients[0].resizeSession,true,'Storage failures do not break the current session');
 for(const item of [reopened,other,denied])item.events.get('pagehide')();
 console.log('Console fixed/graphical profiles, 350ms resize settling, persistence, fullscreen, 1:1, stale callbacks and observer cleanup passed.');
})();
