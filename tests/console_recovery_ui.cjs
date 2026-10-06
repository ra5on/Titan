'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('titan/web/console.js','utf8').replace("import('/novnc/core/rfb.js')",'loadRFB()');
const turns=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
(async()=>{
 const nodes=new Map(),timers=new Map(),instances=[],events=new Map();let next=0,response={ok:true,status:200,json:async()=>({ready:true})},requests=0;
 function node(id){if(!nodes.has(id))nodes.set(id,{textContent:'',disabled:false,handlers:new Map(),addEventListener(k,f){this.handlers.set(k,f);},remove(){}});return nodes.get(id);}
 class RFB{constructor(screen,url){this.url=url;this.handlers=new Map();this.keys=[];instances.push(this);}addEventListener(k,f){this.handlers.set(k,f);}emit(k){this.handlers.get(k)?.();}disconnect(){this.disconnected=true;this.emit('disconnect');}sendKey(...args){this.keys.push(args);}focus(){this.focused=true;}sendCtrlAltDel(){this.cad=true;}}
 const ctx={URLSearchParams,location:{search:'?vm=fixture&embedded=1',protocol:'https:',host:'nas.local:5000'},document:{querySelector:node},window:{addEventListener:(k,f)=>events.set(k,f)},fetch:async url=>{assert(url.startsWith('/api/vm-console?vm=fixture'));requests++;return response;},loadRFB:async()=>({default:RFB}),setTimeout:(f,ms)=>{const id=++next;timers.set(id,{f,ms});return id;},clearTimeout:id=>timers.delete(id)};
 vm.runInNewContext(source,ctx);await turns();assert.equal(instances.length,1);const first=instances[0];assert.match(first.url,/wss:\/\/nas.local:5000\/api\/vnc/);first.emit('connect');assert.equal(node('#console-status').textContent,'Verbunden');assert.deepEqual(first.keys,[[0xffe1,'ShiftLeft',true],[0xffe1,'ShiftLeft',false]]);assert(first.focused);assert(!first.cad);
 first.emit('disconnect');assert.equal(timers.size,1);assert.match(node('#console-status').textContent,/erneuter Verbindungsaufbau/);const pending=[...timers.values()][0];pending.f();await turns();assert.equal(instances.length,2);assert.equal(requests,2);
 response={ok:false,status:403,json:async()=>({error:'Forbidden'})};node('#reconnect').handlers.get('click')();await turns();assert.equal(timers.size,0);assert.match(node('#console-status').textContent,/Administrator anmelden/);assert.equal(node('#reconnect').disabled,false);
 response={ok:false,status:400,json:async()=>({error:'VM muss laufen'})};node('#reconnect').handlers.get('click')();await turns();assert.equal(timers.size,1);assert.match(node('#console-status').textContent,/VM muss laufen/);events.get('pagehide')();assert.equal(timers.size,0);
 console.log('Console automatic preflight, wake, reconnection, auth errors and cleanup passed.');
})();
