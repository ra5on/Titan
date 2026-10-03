'use strict';
// Verify card identity, keyboard / pointer ordering and per-account persistence.
const assert=require('node:assert/strict');
const dashboard=require('../titan/web/dashboard.js');
const fs=require('node:fs');
const vm=require('node:vm');
const turns=()=>new Promise(resolve=>setImmediate(resolve));
const camel=text=>text.replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());
class Element {
 constructor(tag='div',attributes={}){
  this.tag=tag;this.attributes=attributes;this.dataset={};this.children=[];this.parent=null;this.hidden=false;this.disabled=false;this.style={};this.events=new Map();this.textContent='';this.innerHTML='kept-card-content';
  for(const [name,value]of Object.entries(attributes))if(name.startsWith('data-'))this.dataset[camel(name.slice(5))]=value;
  this.classes=new Set((attributes.class||'').split(' ').filter(Boolean));
  this.classList={toggle:(name,value)=>{if(value===undefined)value=!this.classes.has(name);value?this.classes.add(name):this.classes.delete(name);},add:name=>this.classes.add(name),remove:name=>this.classes.delete(name)};
 }
 append(...nodes){for(const node of nodes){if(node.parent)node.parent.children=node.parent.children.filter(child=>child!==node);node.parent=this;const assign=child=>{child.ownerDocument=this.ownerDocument;child.children.forEach(assign);};assign(node);this.children.push(node);}}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this);this.parent=null;}
 matches(selector){
  if(selector.startsWith('#'))return this.attributes.id===selector.slice(1);
  if(selector.startsWith('.'))return this.classes.has(selector.slice(1));
  const attribute=selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
  if(attribute)return attribute[1] in this.attributes&&(attribute[2]===undefined||this.attributes[attribute[1]]===attribute[2]);
  return this.tag===selector;
 }
 querySelectorAll(selector){return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 closest(selector){return this.matches(selector)?this:this.parent?.closest(selector)||null;}
 contains(node){return node===this||this.children.some(child=>child.contains(node));}
 addEventListener(name,callback){this.events.set(name,callback);}
 removeEventListener(name,callback){if(this.events.get(name)===callback)this.events.delete(name);}
 dispatch(name,event){event.type=name;this.events.get(name)?.(event);}
 setAttribute(name,value){this.attributes[name]=value;}
 focus(){this.ownerDocument.activeElement=this;}
 setPointerCapture(id){this.pointer=id;}
 releasePointerCapture(){this.pointer=null;}
 getBoundingClientRect(){return {top:100,height:100};}
}
function fixture(){
 const doc=new Element('document');doc.ownerDocument=doc;doc.createElement=tag=>{const node=new Element(tag);node.ownerDocument=doc;return node;};
 doc.body=new Element('body');doc.body.ownerDocument=doc;doc.defaultView={innerHeight:800,scrollBy(){}};doc.elementFromPoint=()=>doc.hit;
 const main=new Element('main');main.ownerDocument=doc;
 const grid=new Element('div',{id:'dashboard-grid'});main.append(grid);
 for(const attr of ['data-layout-edit','data-layout-reset','data-layout-cancel','data-layout-save'])main.append(new Element('button',{[attr]:''}));
 for(const id of ['dashboard-layout-hint','dashboard-layout-announcement'])main.append(new Element('p',{id}));
 const tiles={};
 for(const id of dashboard.ids){
  const tile=new Element('section',{'data-dashboard-tile':id}),header=new Element('h2'),controls=new Element('div',{class:'tile-controls'});
  header.textContent=id;
  controls.append(new Element('button',{'data-layout-handle':id}),new Element('button',{'data-layout-move':'-1'}),new Element('button',{'data-layout-move':'1'}));
  tile.append(header,controls);grid.append(tile);tiles[id]=tile;
 }
 const order=()=>grid.children.map(tile=>tile.dataset.dashboardTile);
 const click=selector=>main.dispatch('click',{target:main.querySelector(selector)});
 const key=(id,key)=>{let prevented=false;main.dispatch('keydown',{target:tiles[id].querySelector('[data-layout-handle]'),key,preventDefault(){prevented=true;}});return prevented;};
 return {doc,main,grid,tiles,order,click,key};
}
(async()=>{
 assert.deepEqual(dashboard.normalize(['vms','vms','unknown','storage']),['vms','storage','tools','resources','health','apps','shares']);
 assert.deepEqual(dashboard.normalize(null),dashboard.ids);
 assert.deepEqual(dashboard.move(dashboard.ids,'vms',0),['vms','tools','storage','resources','health','apps','shares']);
 assert.deepEqual(dashboard.move(dashboard.ids,'storage',100),['tools','resources','health','apps','shares','vms','storage']);
 assert.deepEqual(dashboard.move(dashboard.ids,'unknown',0),dashboard.ids);
 const fetched=[];
 const layoutAPI=async path=>{fetched.push(path);return {order:['shares','storage']};};
 assert.deepEqual((await dashboard.load(layoutAPI,'first')).order,['shares','storage','tools','resources','health','apps','vms']);
 await dashboard.load(layoutAPI,'first');assert.equal(fetched.length,1);
 await dashboard.load(layoutAPI,'second');assert.equal(fetched.length,2);
 const fallback=await dashboard.load(async()=>{throw Error('temporary error');},'offline');
 assert.equal(fallback.available,false);assert.deepEqual(fallback.order,dashboard.ids);
 const view=fixture(),requests=[],notices=[];let rejectSave=true;
 dashboard.mount(view.main,{owner:'first',toast:(text,error)=>notices.push({text,error}),api:async(path,body)=>{
  requests.push({path,body});if(rejectSave)throw Error('network unavailable');return body;
 }});
 view.click('[data-layout-edit]');assert(dashboard.editing());
 assert.equal(view.tiles.storage.querySelector('.tile-controls').hidden,false);
 assert.equal(view.doc.activeElement,view.tiles.tools.querySelector('[data-layout-handle]'));
 assert(view.key('vms','Home'));assert.equal(view.order()[0],'vms');
 assert(view.key('storage','ArrowDown'));assert.equal(view.order()[3],'storage');
 assert(view.key('vms','End'));assert.equal(view.order().at(-1),'vms');
 assert(!view.key('vms','a'));
 view.main.dispatch('click',{target:view.tiles.vms.querySelector('[data-layout-move="-1"]')});
 assert.equal(view.order().at(-2),'vms');
 // Pointer reordering uses mouse or touch handles, preserves card contents, and supports cancellation.
 const handle=view.tiles.vms.querySelector('[data-layout-handle]');
 const pointer={target:handle,pointerId:7,button:0,isPrimary:true,clientX:100,clientY:100,preventDefault(){}};
 view.grid.dispatch('pointerdown',pointer);view.doc.hit=view.tiles.storage;
 view.doc.dispatch('pointermove',{...pointer,clientY:120});
 assert.equal(view.order()[2],'vms');assert.equal(view.doc.body.children.length,1);
 view.doc.dispatch('pointercancel',pointer);
 assert.equal(view.order().at(-2),'vms');assert.equal(view.doc.body.children.length,0);
 view.grid.dispatch('pointerdown',pointer);view.doc.hit=view.tiles.storage;
 view.doc.dispatch('pointermove',{...pointer,clientY:120});view.doc.dispatch('pointerup',pointer);
 assert.equal(view.order()[2],'vms');assert.equal(view.doc.body.children.length,0);
 assert.equal(view.tiles.vms.innerHTML,'kept-card-content');
 assert.equal(view.grid.children.find(tile=>tile.dataset.dashboardTile==='vms'),view.tiles.vms);
 const draft=view.order();view.click('[data-layout-save]');await turns();
 assert(dashboard.editing());assert.deepEqual(view.order(),draft);assert.equal(notices.at(-1).error,true);
 assert.equal(view.main.querySelector('[data-layout-save]').disabled,false);
 rejectSave=false;view.click('[data-layout-save]');await turns();
 assert(!dashboard.editing());assert.deepEqual(requests.at(-1),{path:'/api/dashboard-layout',body:{order:draft,hidden:[],wide:["tools","resources"]}});
 assert.deepEqual((await dashboard.load(layoutAPI,'first')).order,draft);
 assert.deepEqual((await dashboard.load(layoutAPI,'second')).order,['shares','storage','tools','resources','health','apps','vms']);
 view.click('[data-layout-edit]');view.click('[data-layout-reset]');assert.deepEqual(view.order(),dashboard.ids);
 view.click('[data-layout-cancel]');assert.deepEqual(view.order(),draft);assert(!dashboard.editing());
 // Navigating away releases pointer listeners and a stale response does not touch the next page.
 view.click('[data-layout-edit]');view.grid.dispatch('pointerdown',pointer);view.doc.hit=view.tiles.storage;
 view.doc.dispatch('pointermove',{...pointer,clientY:120});dashboard.dispose();
 assert.equal(view.doc.body.children.length,0);assert.equal(view.doc.events.size,0);assert(!dashboard.editing());
 dashboard.clear();await dashboard.load(layoutAPI,'first');assert.equal(fetched.length,3);
 const markup=dashboard.toolbar()+dashboard.controls('storage','Speicher');
 assert(markup.includes('role="status"'));assert(markup.includes('data-layout-save'));assert(markup.includes('Pfeiltasten'));
 // Layout saves retain the application CSRF boundary after removing the old drawer.
 const nodes=new Map(),callbacks={},browserCallbacks={};let small=true;
 const doc={querySelector:selector=>{
  if(!nodes.has(selector)){const node=new Element('div',selector.startsWith('#')?{id:selector.slice(1)}:{class:selector.slice(1)});node.ownerDocument=doc;nodes.set(selector,node);}return nodes.get(selector);
 },querySelectorAll:()=>[],addEventListener:(name,callback)=>callbacks[name]=callback};
 doc.body=new Element('body');doc.body.ownerDocument=doc;
 const browser={addEventListener:(name,callback)=>browserCallbacks[name]=callback,matchMedia:query=>({matches:query.includes('max-width')?small:!small}),TitanDashboard:dashboard};
 const context=vm.createContext({document:doc,window:browser,location:{hash:'#dashboard'},setTimeout:()=>0,setInterval:()=>0,clearInterval(){},console});
 const source=fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,'');
 vm.runInContext(source,context);
 const evaluate=expression=>vm.runInContext(expression,context);
 // Layout saves use the application's same-origin JSON and session CSRF handling.
 evaluate("session={user:{name:'first',csrf:'synthetic-layout-csrf'}}");
 let persisted;
 context.fetch=async(path,options)=>{persisted={path,options};return {ok:true,json:async()=>({order:dashboard.ids})};};
 await evaluate("api('/api/dashboard-layout',{order:['vms','storage']})");
 assert.equal(persisted.path,'/api/dashboard-layout');assert.equal(persisted.options.method,'POST');
 assert.equal(persisted.options.headers['X-CSRF-Token'],'synthetic-layout-csrf');
 assert.deepEqual(JSON.parse(persisted.options.body),{order:['vms','storage']});
 console.log('Dashboard layout: complete IDs, account cache, keyboard, pointer/cancel, preserved nodes, retry/save/reset and cleanup passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
