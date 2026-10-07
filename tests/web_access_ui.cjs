'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let interval,cleared=false;
const context=vm.createContext({window:{},Date,setInterval(fn){interval=fn;return 42;},clearInterval(id){assert.equal(id,42);cleared=true;},FormData:class{constructor(){this.values={mode:'http',http_port:'8080',https_port:'8443'};}get(key){return this.values[key];}}});
vm.runInContext(fs.readFileSync('titan/web/web_access.js','utf8'),context);
const ui=context.window.TitanWebAccess;
const data={settings:{mode:'https',http_port:80,https_port:443},revision:'r1',origin:'https://nas.test',certificate:{label:'Lokales Zertifikat'}};
const html=ui.render(data);
assert(html.includes('name="http_port"'));assert(html.includes('name="https_port"'));assert(html.includes('HTTP wird automatisch auf HTTPS weitergeleitet'));
assert(!ui.render({...data,settings:{...data.settings,mode:'http'}}).includes('HTTP wird automatisch auf HTTPS weitergeleitet'));
const hostile=ui.render({...data,last_error:'<script>bad()</script>',certificate:{label:'<bad>'}});
assert(!hostile.includes('<script>'));assert(hostile.includes('&lt;script&gt;'));assert(hostile.includes('&lt;bad&gt;'));
class Node{
 constructor(){this.events=new Map();this.hidden=false;this.disabled=false;this.textContent='';this.value='https';}
 addEventListener(event,fn){this.events.set(event,fn);}
 removeEventListener(event,fn){if(this.events.get(event)===fn)this.events.delete(event);}
}
function fixture(value,here){
 const fields=[new Node(),new Node(),new Node()],form=new Node();form.elements={mode:fields[0]};
 const nodes=new Map(['data-web-access-status','data-web-access-error','data-web-pending','data-web-confirm','data-web-open','data-web-cancel','data-web-deadline','data-web-redirect-note'].map(key=>['['+key+']',new Node()]));
 nodes.set('[data-web-access-form]',form);
 const panel={dataset:{config:JSON.stringify(value)},querySelector:s=>nodes.get(s),querySelectorAll:()=>fields};
 const scope={querySelector:()=>panel,ownerDocument:{defaultView:{location:{origin:here}}}};
 return {scope,nodes,form,fields};
}
(async()=>{
 const pending={...data,pending:true,deadline:Date.now()/1000+120};
 let f=fixture(pending,'http://nas.test');ui.mount(f.scope,{api:async()=>pending});
 assert.equal(f.nodes.get('[data-web-confirm]').hidden,true);assert.equal(f.nodes.get('[data-web-open]').hidden,false);assert(f.fields.every(n=>n.disabled));
 f=fixture({...pending,confirming:true},data.origin);ui.mount(f.scope,{api:async()=>pending});
 assert.equal(f.nodes.get('[data-web-confirm]').hidden,false);assert.equal(f.nodes.get('[data-web-confirm]').disabled,true);assert.equal(f.nodes.get('[data-web-open]').hidden,true);assert(f.nodes.get('[data-web-access-status]').textContent.includes('aktiviert'));
 let calls=[],finish,refreshed=0;
 f=fixture(data,data.origin);ui.mount(f.scope,{api:(route,body)=>{calls.push({route,body});return new Promise(resolve=>finish=resolve);},refresh(){refreshed++;}});
 const submit=f.form.events.get('submit');submit({preventDefault(){}});submit({preventDefault(){}});
 assert.equal(calls.length,1,'Repeated submit cannot race endpoint updates');assert.equal(calls[0].body.settings.http_port,8080);assert.equal(calls[0].body.settings.https_port,8443);assert.equal(calls[0].body.expected_revision,'r1');
 ui.dispose();finish(pending);await Promise.resolve();await Promise.resolve();assert.equal(refreshed,0,'Disposed responses cannot navigate/repaint');assert(cleared);assert.equal(f.form.events.size,0);
 console.log('Web access UI: protocol/ports, redirect, escaping, pending/current-origin confirmation, activation, duplicate-submit protection and cleanup passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
