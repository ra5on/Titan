'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('titan/web/console.js','utf8').replace("import('/novnc/core/rfb.js')",'loadRFB()');
const turns=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function accountThemeFixture({embedded=false,layoutResponse,late=false}={}){
 const nodes=new Map(),events=new Map(),applied=[],calls=[];let resolveLayout;
 const account=late?new Promise(resolve=>resolveLayout=resolve):Promise.resolve(layoutResponse||{ok:true,json:async()=>({desktop:{color_mode:'dark',transparency:27}})});
 const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',handlers:new Map(),addEventListener(name,handler){this.handlers.set(name,handler);}});return nodes.get(id);};
 const context={URLSearchParams,location:{search:'?vm=theme-vm'+(embedded?'&embedded=1':''),protocol:'https:',host:'nas.local'},document:{body:{dataset:{}},querySelector:node,addEventListener(){},removeEventListener(){}},window:{TitanTheme:{set:value=>applied.push(value)},AbortController,addEventListener:(name,handler)=>events.set(name,handler),removeEventListener(){}},fetch:(url,options)=>{calls.push({url,options});if(url==='/api/launcher-layout')return account;return Promise.resolve({ok:false,status:403,json:async()=>({error:'not ready'})});},setTimeout(){return 1;},clearTimeout(){}};
 vm.runInNewContext(source,context);
 return {node,applied,calls,events,resolveLayout};
}
async function verifyAccountThemeLifecycle(){
 let f=accountThemeFixture();await turns();assert.deepEqual(f.applied,[{color_mode:'dark',transparency:27}]);
 const read=f.calls.find(call=>call.url==='/api/launcher-layout');assert.equal(read.options.credentials,'same-origin');assert.equal(read.options.cache,'no-store');assert.equal(read.options.method,undefined,'Account appearance is read-only');
 f.node('#reconnect').handlers.get('click')();await turns();assert.equal(f.calls.filter(call=>call.url==='/api/launcher-layout').length,1,'Reconnecting a VM does not refetch or reset the account appearance');
 f.events.get('pagehide')();assert.equal(read.options.signal.aborted,true);

 f=accountThemeFixture({embedded:true});await turns();assert.equal(f.applied.length,0);assert(!f.calls.some(call=>call.url==='/api/launcher-layout'),'Embedded console leaves the live parent theme authoritative');f.events.get('pagehide')();
 f=accountThemeFixture({layoutResponse:{ok:false,json:async()=>{throw Error('must not parse unauthorized account');}}});await turns();assert.equal(f.applied.length,0);f.events.get('pagehide')();
 f=accountThemeFixture({layoutResponse:{ok:true,json:async()=>{throw Error('invalid JSON');}}});await turns();assert.equal(f.applied.length,0,'An invalid appearance response leaves the console usable');f.events.get('pagehide')();

 f=accountThemeFixture({late:true});const lateRead=f.calls.find(call=>call.url==='/api/launcher-layout');f.events.get('pagehide')();assert(lateRead.options.signal.aborted);f.resolveLayout({ok:true,json:async()=>({desktop:{color_mode:'light'}})});await turns();assert.equal(f.applied.length,0,'Closed console ignores a late account appearance response');
}
(async()=>{
 const nodes=new Map(),timers=new Map(),instances=[],events=new Map();let next=0,response={ok:true,status:200,json:async()=>({ready:true})},requests=0;
 function node(id){if(!nodes.has(id))nodes.set(id,{textContent:'',disabled:false,handlers:new Map(),addEventListener(k,f){this.handlers.set(k,f);},remove(){}});return nodes.get(id);}
 class RFB{constructor(screen,url){this.url=url;this.handlers=new Map();this.keys=[];instances.push(this);}addEventListener(k,f){this.handlers.set(k,f);}emit(k){this.handlers.get(k)?.();}disconnect(){this.disconnected=true;this.emit('disconnect');}sendKey(...args){this.keys.push(args);}focus(){this.focused=true;}sendCtrlAltDel(){this.cad=true;}}
 const ctx={URLSearchParams,location:{search:'?vm=fixture&embedded=1',protocol:'https:',host:'nas.local:5000'},document:{body:{dataset:{}},querySelector:node,addEventListener(){},removeEventListener(){}},window:{addEventListener:(k,f)=>events.set(k,f),removeEventListener:k=>events.delete(k)},fetch:async url=>{assert(url.startsWith('/api/vm-console?vm=fixture'));requests++;return response;},loadRFB:async()=>({default:RFB}),setTimeout:(f,ms)=>{const id=++next;timers.set(id,{f,ms});return id;},clearTimeout:id=>timers.delete(id)};
 vm.runInNewContext(source,ctx);await turns();assert.equal(instances.length,1);const first=instances[0];assert.match(first.url,/wss:\/\/nas.local:5000\/api\/vnc/);first.emit('connect');assert.equal(node('#console-status').textContent,'Verbunden');assert.equal(node('#console-connection').hidden,true);assert.equal(ctx.document.body.dataset.connection,'connected');assert.deepEqual(first.keys,[[0xffe1,'ShiftLeft',true],[0xffe1,'ShiftLeft',false]]);assert(first.focused);assert(!first.cad);
 first.emit('disconnect');assert.equal(timers.size,1);assert.match(node('#connection-message').textContent,/erneuter Verbindungsaufbau/);const pending=[...timers.values()][0];pending.f();await turns();assert.equal(instances.length,2);assert.equal(requests,2);
 response={ok:false,status:403,json:async()=>({error:'Forbidden'})};node('#reconnect').handlers.get('click')();await turns();assert.equal(timers.size,0);assert.match(node('#connection-message').textContent,/Administrator anmelden/);assert.equal(node('#reconnect').disabled,false);
 response={ok:false,status:400,json:async()=>({error:'VM muss laufen'})};node('#reconnect').handlers.get('click')();await turns();assert.equal(timers.size,1);assert.match(node('#connection-message').textContent,/VM muss laufen/);events.get('pagehide')();assert.equal(timers.size,0);
 await verifyAccountThemeLifecycle();
 console.log('Console automatic preflight, wake, reconnection, auth errors, account theme authority, request failure tolerance, abort and cleanup passed.');
})();
