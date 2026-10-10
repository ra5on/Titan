'use strict';
const assert=require('node:assert/strict');
const ui=require('../titan/web/umbrel_store.js');
const {fixture:domFixture}=require('./desktop_test_dom.cjs');
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const app={id:'example',name:'Example <script>',description:'Private notes',category:'Notes',umbrel_catalog:true,default_port:5230,containers:1,install_schema:[]};
function fixture(extra={}){
 const f=domFixture(),scope=f.doc.createElement('section');f.doc.body.append(scope);
 const context={catalog:{apps:[app],umbrel:{loaded:true,total:2,blocked:[{id:'other',name:'<Other>',reason:'<required>'}]}},installed:{installed:[]},admin:true,demo:false,...extra};
 const html=ui.render(context);scope.innerHTML=html;let reloads=0,dialog=null;const calls=[],requests=[];
 const ctx={admin:context.admin,demo:context.demo,api:async path=>{requests.push(path);if(path==='/api/catalog')return context.catalog;if(path==='/api/apps')return context.installed;if(path==='/api/storage-locations')return {default_storage:'disk',storage:[{id:'disk',label:'Data',capabilities:['apps']}]};throw Error(path);},action:async(...args)=>{calls.push(args);return {ok:true};},reload:()=>reloads++,dialog:(...args)=>dialog=args,toast:()=>{},openPackage:id=>calls.push(['manage',id])};
 ui.mount(scope,ctx);
 return {...f,scope,context,ctx,calls,requests,html,click:selector=>f.doc.dispatch(scope.querySelector(selector),'click'),get dialog(){return dialog;},get reloads(){return reloads;}};
}
(async()=>{
 let f=fixture();assert.match(f.html,/Example &lt;script&gt;/);assert.match(f.html,/&lt;required&gt;/);assert(!f.html.includes('<script>'));assert.equal(f.scope.querySelectorAll('[data-umbrel-app]').length,1);
 f.click('[data-umbrel-refresh]');await settle();assert.equal(f.calls[0][0],'app_store_refresh');assert.deepEqual(f.calls[0][1],{store:'umbrel'});assert.equal(f.reloads,1);ui.dispose();
 f=fixture();f.click('[data-umbrel-app]');await settle();assert(f.dialog);const values=new Map([['port','5230'],['storage_id','disk']]);await f.dialog[2](values);assert.equal(f.calls[0][0],'app_install');assert.deepEqual(f.calls[0][1],{app:'example',port:5230,storage_id:'disk',options:{}});assert.equal(f.reloads,1);ui.dispose();
 f=fixture({catalog:{apps:[{...app,retained_installation:true,retained_storage_id:'disk'}],umbrel:{loaded:true}}});f.click('[data-umbrel-app]');await settle();assert(f.dialog);assert.match(f.dialog[1],/zuletzt installierten App-Version/);assert.match(f.dialog[1],/value="disk"/);ui.dispose();
 f=fixture({catalog:{apps:[{...app,retained_installation:true,retained_storage_id:'offline'}],umbrel:{loaded:true}}});f.click('[data-umbrel-app]');await settle();assert.equal(f.dialog,null);assert.match(f.scope.textContent,/bisherige App-Speicher ist nicht verfügbar/);assert.equal(f.calls.length,0);ui.dispose();
 f=fixture({installed:{installed:[{id:'example'}]}});f.click('[data-umbrel-app]');await settle();assert.deepEqual(f.calls,[['manage','example']]);assert.equal(f.dialog,null);ui.dispose();
 for(const extra of [{admin:false},{demo:true}]){f=fixture(extra);assert(f.scope.querySelector('[data-umbrel-refresh]').disabled);f.click('[data-umbrel-app]');await settle();assert.equal(f.requests.length,0);ui.dispose();}
 f=fixture();const input=f.scope.querySelector('[data-umbrel-search]');input.value='missing';f.doc.dispatch(input,'input');assert(f.scope.querySelector('[data-umbrel-card]').hidden);assert(!f.scope.querySelector('[data-umbrel-empty]').hidden);input.value='notes';f.doc.dispatch(input,'input');assert(!f.scope.querySelector('[data-umbrel-card]').hidden);ui.dispose();
 f=fixture();let finish;f.ctx.action=()=>new Promise(resolve=>finish=resolve);f.click('[data-umbrel-refresh]');ui.dispose();finish({ok:true});await settle();assert.equal(f.reloads,0);
 f=fixture({catalog:{apps:[],umbrel:{loaded:false,total:0}}});await settle();assert.equal(f.calls.length,1);assert.equal(f.calls[0][0],'app_store_refresh');assert.equal(f.reloads,1);ui.dispose();
 // One main search/category/installed filter covers both store sources.
 const mainUI=require('../titan/web/apps_center.js');
 f=fixture({demo:true,installed:{installed:[{id:'example',name:'Example'}]}});ui.dispose();
 const context={...f.context,integrated:true};
 f.scope.innerHTML=mainUI.render(context)+ui.render(context);
 mainUI.mount(f.scope,{admin:true,demo:true});ui.mount(f.scope,f.ctx);
 assert.equal(f.scope.querySelector('[data-umbrel-search]'),null);
 assert.equal(f.scope.querySelectorAll('[data-store-card="example"]').length,1,'Installed catalog app is not duplicated');
 const sharedSearch=f.scope.querySelector('[data-store-search]');sharedSearch.value='private notes';f.doc.dispatch(sharedSearch,'input');
 assert.equal(f.scope.querySelector('[data-store-result]').textContent,'1 App');
 assert.equal(f.scope.querySelector('[data-umbrel-card]').hidden,false);
 sharedSearch.value='';f.doc.dispatch(sharedSearch,'input');
 f.doc.dispatch(f.scope.querySelector('[data-store-category="network"]'),'click');
 assert.equal(f.scope.querySelector('[data-umbrel-card]').hidden,true);
 f.doc.dispatch(f.scope.querySelector('[data-store-category="installed"]'),'click');
 assert.equal(f.scope.querySelector('[data-umbrel-card]').hidden,false);
 assert.equal(f.scope.querySelector('[data-store-result]').textContent,'1 App');
 mainUI.dispose();ui.dispose();
 console.log('Umbrel storefront: escaping, refresh, installation, management, permissions, search and disposal passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
