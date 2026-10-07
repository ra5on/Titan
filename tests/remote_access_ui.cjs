'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ui=require('../titan/web/remote_access.js');
const data={revision:'revision-one',remote:{enabled:true,public_origin:'https://nas.example.de',connector:'cloudflare',service_url:'http://172.30.0.1:5102',sources:['172.30.0.0/24'],app_urls:{}},connectors:[{id:'cloudflare',name:'Cloudflare <Web>'}],apps:[{id:'photos',name:'Photos <private>'}]};
const markup=ui.render(data);
assert.match(markup,/http:\/\/172\.30\.0\.1:5102/);assert.match(markup,/Cloudflare &lt;Web&gt;/);assert.match(markup,/Photos &lt;private&gt;/);assert.match(markup,/data-remote-app="photos"/);
assert.match(ui.render({...data,demo:true}),/name="enabled" checked disabled/);
assert.match(ui.checks({checked_at:1,checks:[{name:'<route>',ok:false,message:'<blocked>'}]}),/&lt;blocked&gt;/);
function fixture(){
 const nodes=new Map(),inputs=[{dataset:{remoteApp:'photos'},value:' https://photos.example.de/ '},{dataset:{remoteApp:'unused'},value:' '}],controls=[...inputs,{disabled:false}];
 const form={elements:{enabled:{checked:true},public_origin:{value:' https://nas.example.de '},connector:{value:'cloudflare'}}};
 nodes.set('[data-remote-form]',form);for(const selector of ['[data-remote-error]','[data-remote-status]','[data-remote-diagnose]'])nodes.set(selector,{hidden:true,textContent:'',disabled:false});
 const panel={dataset:{config:JSON.stringify(data)},querySelector:selector=>nodes.get(selector),querySelectorAll:selector=>selector==='[data-remote-app]'?inputs:controls};
 const events=new Map(),scope={querySelector:()=>panel,addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:(name,fn)=>{if(events.get(name)===fn)events.delete(name);}};
 return {scope,nodes,panel,events,controls};
}
(async()=>{
 let f=fixture(),calls=[],finish;
 ui.mount(f.scope,{api:(path,body)=>{calls.push({path,body});return new Promise(resolve=>finish=resolve);}});
 const submit={target:{matches:()=>true},preventDefault(){}};
 f.events.get('submit')(submit);f.events.get('submit')(submit);
 assert.equal(calls.length,1,'Saving twice must not race firewall and proxy changes');
 assert.deepEqual(calls[0],{path:'/api/remote-access',body:{enabled:true,public_origin:'https://nas.example.de',connector:'cloudflare',app_urls:{photos:'https://photos.example.de/'},expected_revision:'revision-one'}});
 assert(f.controls.every(node=>node.disabled));
 ui.dispose();assert.equal(f.events.size,0);finish(data);await Promise.resolve();await Promise.resolve();
 assert.equal(f.panel.outerHTML,undefined,'An obsolete save response must not repaint another settings view');
 f=fixture();ui.mount(f.scope,{api:async()=>{throw Error('Revision geändert');}});f.events.get('submit')(submit);await Promise.resolve();await Promise.resolve();
 assert.equal(f.nodes.get('[data-remote-error]').textContent,'Revision geändert');assert.equal(f.nodes.get('[data-remote-error]').hidden,false);assert(f.controls.every(node=>!node.disabled));ui.dispose();
 const context={window:{location:{origin:'http://192.168.1.2'}},URL,console,FormData,setInterval:()=>1,clearInterval(){},setTimeout};vm.createContext(context);vm.runInContext(fs.readFileSync('titan/web/app_networks.js','utf8'),context);
 const app={titan_public_origin:'https://nas.example.de',endpoints:[{scope:'lan',url:'http://192.168.1.2:8080/'},{scope:'public',url:'https://photos.example.de/'}]};
 assert.equal(context.window.TitanNetworks.connection(app),'http://192.168.1.2:8080/');context.window.location.origin='https://nas.example.de';
 assert.equal(context.window.TitanNetworks.connection(app),'https://photos.example.de/');
 assert.equal(context.window.TitanNetworks.connection({...app,endpoints:app.endpoints.slice(0,1)}),'','Remote clients must not receive an unusable private fallback');
 assert.equal(context.window.TitanNetworks.connection({...app,web_state:'stopped'}),'');
 console.log('Remote access UI: optional addresses, escaped output, revision-bound save, duplicate protection, disposal, recoverable errors and explicit LAN/public links passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
