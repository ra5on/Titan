'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),{setMaxListeners}=require('node:events'),ui=require('../titan/web/sidebar_layout.js');
setMaxListeners(0);
const values=new Map(),storage={getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)};
global.localStorage=storage;
const inspectorOptions={width:320,min:240,max:520,content:320};
assert.equal(ui.normalize(NaN),160);assert.equal(ui.normalize('320'),160);assert.equal(ui.normalize(999),360);assert.equal(ui.normalize(-30),128);
ui.save('alice','settings',286);assert.equal(ui.load('alice','settings'),286);assert.equal(ui.load('bob','settings'),160);assert.equal(ui.load('alice','storage'),160);
values.set('titan-sidebar-layout:broken:settings','{oops');assert.equal(ui.load('broken','settings'),160);assert.equal(ui.load('alice','settings',undefined,{getItem(){throw Error('blocked');}}),160);
assert.equal(ui.save('alice','blocked',200,undefined,{setItem(){throw Error('blocked');}}),200);
assert.equal(ui.widthFor(360,590),270);assert.deepEqual(ui.bounds(200),{min:0,max:0});assert.equal(ui.widthFor(160,200),0);
class Node{
 constructor(classes='',dataset={}){this.className=classes;this.dataset=dataset;this.children=[];this.parentNode=null;this.attrs={};this.events=new Map();this.clientWidth=1200;this.css={};this.style={setProperty:(key,value)=>this.css[key]=value,removeProperty:key=>delete this.css[key]};this.classList={contains:name=>this.className.split(' ').includes(name),add:name=>{if(!this.classList.contains(name))this.className+=' '+name;},remove:name=>this.className=this.className.split(' ').filter(value=>value!==name).join(' ')};}
 matches(selector){const cls=selector.match(/^\.([\w-]+)/),attr=selector.match(/\[([\w-]+)(?:=([^\]]+))?\]/);return (!cls||this.classList.contains(cls[1]))&&(!attr||(attr[1].startsWith('data-')?this.dataset[attr[1].slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]!==undefined:this.attrs[attr[1]]!==undefined)&&(!attr[2]||(attr[1]==='role'?this.attrs.role:this.dataset[attr[1].slice(5)])===attr[2]));}
 querySelectorAll(selector){return this.children.flatMap(node=>[...(node.matches(selector)?[node]:[]),...node.querySelectorAll(selector)]);}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 closest(selector){return this.matches(selector)?this:this.parentNode?.closest(selector)||null;}
 contains(node){return node===this||this.children.some(child=>child.contains(node));}
 appendChild(node){node.parentNode=this;node.ownerDocument=this.ownerDocument;this.children.push(node);return node;}
 remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(node=>node!==this);this.parentNode=null;}
 setAttribute(key,value){this.attrs[key]=value;}getAttribute(key){return this.attrs[key]??null;}
 addEventListener(type,fn,options={}){const set=this.events.get(type)||new Set();set.add(fn);this.events.set(type,set);options.signal?.addEventListener('abort',()=>set.delete(fn),{once:true});}
 removeEventListener(type,fn){this.events.get(type)?.delete(fn);}
 fire(type,event={}){event.preventDefault??=()=>event.prevented=true;for(const handler of this.events.get(type)||[])handler(event);return event;}
 setPointerCapture(id){this.captured=id;}releasePointerCapture(id){this.released=id;}
}
let frames=new Map(),frameId=0,mutation=null;const observers=new Set(),media=new Node();media.matches=false;
const doc={createElement:()=>new Node(),defaultView:{matchMedia:()=>media,requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id),ResizeObserver:class{constructor(fn){this.fn=fn;observers.add(this);}observe(node){this.node=node;}disconnect(){observers.delete(this);}},MutationObserver:class{constructor(fn){mutation=fn;}observe(){}disconnect(){mutation=null;}}}};
function flush(){const current=[...frames.values()];frames.clear();current.forEach(fn=>fn());}
function root(){const node=new Node();node.ownerDocument=doc;return node;}
function workspace(scope,classes,navClass,dataset={}){const element=scope.appendChild(new Node(classes,dataset)),sidebar=element.appendChild(new Node(navClass)),tabs=sidebar.appendChild(new Node());tabs.setAttribute('role','tablist');return {element,sidebar,tabs};}
const scope=root(),settings=workspace(scope,'cp-layout','cp-sidebar'),storagePane=workspace(scope,'storage-workspace','storage-navigation'),vms=workspace(scope,'mv-manager','mv-sidebar',{manager:'vms'}),docker=workspace(scope,'engine-workbench has-inspector','engine-navigation');docker.element.appendChild(new Node('engine-inspector'));
const users=workspace(scope,'um-body','um-detail');
const files=workspace(scope,'fb-browser','fb-places');files.element.appendChild(new Node('fb-splitter'));
const cleanup=ui.mount(scope,{owner:'alice'}),grip=settings.element.querySelector('.titan-sidebar-resizer');
assert.equal(settings.element.css['--titan-sidebar-width'],'286px');assert.equal(vms.element.css['--titan-sidebar-width'],'160px');assert.equal(grip.attrs.role,'separator');assert.equal(grip.attrs['aria-valuenow'],'286');assert.equal(grip.tabIndex,0);assert.equal(files.element.querySelector('.titan-sidebar-resizer'),null);assert.equal(vms.tabs.attrs['aria-orientation'],'vertical');
const userGrip=users.element.querySelector('.titan-sidebar-resizer');assert.equal(users.element.querySelectorAll('.titan-sidebar-resizer').length,1);assert.equal(userGrip.dataset.sidebarResize,'right');assert.equal(userGrip.attrs['aria-valuenow'],'300');userGrip.fire('keydown',{key:'ArrowLeft'});assert.equal(userGrip.attrs['aria-valuenow'],'316');assert.equal(ui.load('alice','users-details',inspectorOptions),316);
assert.equal(grip.fire('keydown',{key:'ArrowLeft'}).prevented,true);assert.equal(ui.load('alice','settings'),270);grip.fire('keydown',{key:'ArrowRight',shiftKey:true});assert.equal(ui.load('alice','settings'),302);
grip.fire('keydown',{key:'Home'});assert.equal(ui.load('alice','settings'),128);grip.fire('keydown',{key:'End'});assert.equal(ui.load('alice','settings'),360);grip.fire('dblclick');assert.equal(ui.load('alice','settings'),164);
// Capture sustains a drag beyond the grip. Pointer IDs and buttons cannot hijack it.
grip.fire('pointerdown',{button:1,pointerId:6,clientX:164});assert.equal(grip.captured,undefined);
grip.fire('pointerdown',{button:0,pointerId:7,clientX:164});assert.equal(grip.captured,7);
grip.fire('pointermove',{pointerId:8,clientX:999});assert.equal(frames.size,0);
grip.fire('pointermove',{pointerId:7,clientX:200});grip.fire('pointermove',{pointerId:7,clientX:264});assert.equal(frames.size,1);flush();assert.equal(grip.attrs['aria-valuenow'],'264');assert.equal(ui.load('alice','settings'),164);
grip.fire('pointerup',{pointerId:8});assert(settings.element.classList.contains('titan-sidebar-resizing'));grip.fire('pointerup',{pointerId:7});assert.equal(ui.load('alice','settings'),264);assert.equal(grip.released,7);assert(!settings.element.classList.contains('titan-sidebar-resizing'));
const right=docker.element.querySelectorAll('.titan-sidebar-resizer').find(item=>item.dataset.sidebarResize==='right');assert.equal(right.attrs['aria-valuenow'],'320');right.fire('keydown',{key:'ArrowLeft'});assert.equal(ui.load('alice','docker-inspector',inspectorOptions),336);right.fire('keydown',{key:'ArrowRight'});assert.equal(ui.load('alice','docker-inspector',inspectorOptions),320);
right.fire('pointerdown',{button:0,pointerId:9,clientX:800});right.fire('pointermove',{pointerId:9,clientX:720});right.fire('pointerup',{pointerId:9});assert.equal(ui.load('alice','docker-inspector',inspectorOptions),400);assert.equal(right.attrs['aria-valuenow'],'400');
right.fire('keydown',{key:'End'});assert.equal(right.attrs['aria-valuenow'],'520');const dockerLeft=docker.element.querySelector('.titan-sidebar-resizer');docker.element.clientWidth=1100;for(const observer of observers)observer.fn();dockerLeft.fire('pointerdown',{button:0,pointerId:10,clientX:160});dockerLeft.fire('pointermove',{pointerId:10,clientX:360});dockerLeft.fire('pointerup',{pointerId:10});assert.equal(dockerLeft.attrs['aria-valuenow'],'360');assert.equal(right.attrs['aria-valuenow'],'420');assert.equal(ui.load('alice','docker-inspector',inspectorOptions),520);right.fire('dblclick');assert.equal(ui.load('alice','docker-inspector',inspectorOptions),320);right.fire('keydown',{key:'ArrowLeft',shiftKey:true});right.fire('keydown',{key:'ArrowLeft',shiftKey:true});right.fire('keydown',{key:'ArrowLeft'});assert.equal(ui.load('alice','docker-inspector',inspectorOptions),400);
// Container limits only affect displayed width; larger desktop preferences survive.
settings.element.clientWidth=550;for(const observer of observers)observer.fn();assert.equal(grip.attrs['aria-valuenow'],'230');assert.equal(ui.load('alice','settings'),264);settings.element.clientWidth=1200;for(const observer of observers)observer.fn();assert.equal(grip.attrs['aria-valuenow'],'264');
docker.element.clientWidth=900;for(const observer of observers)observer.fn();assert.equal(right.tabIndex,-1);right.fire('keydown',{key:'End'});assert.equal(ui.load('alice','docker-inspector',inspectorOptions),400);
// Mobile and VM detail panes remove resize affordances without losing preferences.
media.matches=true;media.fire('change');flush();assert.equal(grip.tabIndex,-1);assert.equal(vms.tabs.attrs['aria-orientation'],'horizontal');grip.fire('pointerdown',{button:0,pointerId:10,clientX:264});assert.equal(grip.captured,7);grip.fire('keydown',{key:'End'});assert.equal(ui.load('alice','settings'),264);
media.matches=false;media.fire('change');flush();vms.element.classList.add('has-vm-detail');mutation([{type:'attributes',attributeName:'class',target:vms.element}]);flush();assert.equal(vms.element.querySelector('.titan-sidebar-resizer').tabIndex,-1);vms.element.classList.remove('has-vm-detail');mutation([{type:'attributes',attributeName:'class',target:vms.element}]);flush();assert.equal(vms.element.querySelector('.titan-sidebar-resizer').tabIndex,0);
// Docker rerenders replace the entire workspace: no stale handles/listeners remain.
const oldLeft=docker.element.querySelector('.titan-sidebar-resizer');docker.element.remove();const replacement=workspace(scope,'engine-workbench has-inspector','engine-navigation');replacement.element.appendChild(new Node('engine-inspector'));mutation([{type:'childList'}]);flush();assert.equal(oldLeft.parentNode,null);for(const listeners of oldLeft.events.values())assert.equal(listeners.size,0);assert.equal(replacement.element.querySelectorAll('.titan-sidebar-resizer').length,2);assert.equal(replacement.element.css['--titan-inspector-width'],'400px');
mutation([{type:'childList'}]);flush();assert.equal(replacement.element.querySelectorAll('.titan-sidebar-resizer').length,2);
// Navigation disposal cancels gestures, pending frames, observers and listeners.
grip.fire('pointerdown',{button:0,pointerId:11,clientX:264});grip.fire('pointermove',{pointerId:11,clientX:280});cleanup();assert.equal(grip.released,11);assert.equal(frames.size,0);assert.equal(observers.size,0);assert.equal(mutation,null);assert.equal(scope.querySelectorAll('.titan-sidebar-resizer').length,0);for(const listeners of grip.events.values())assert.equal(listeners.size,0);for(const listeners of media.events.values())assert.equal(listeners.size,0);
ui.mount(scope,{owner:'bob'});assert.equal(settings.element.css['--titan-sidebar-width'],'164px');ui.dispose();delete global.localStorage;
const css=fs.readFileSync('titan/web/sidebar_layout.css','utf8'),index=fs.readFileSync('titan/web/index.html','utf8'),app=fs.readFileSync('titan/web/app.js','utf8');assert(css.includes('.has-vm-detail{grid-template-columns:minmax(0,1fr)}'));assert(css.includes('@media(max-width:760px){[data-sidebar-layout]>.titan-sidebar-resizer{display:none}}'));assert(index.indexOf('/sidebar_layout.js')<index.indexOf('/app.js'));assert(index.indexOf('/sidebar_layout.css')>index.indexOf('/compact_ui.css'));assert(app.includes("TitanSidebarLayout?.mount($('#main'),{owner:session.user.name})"));assert.equal((app.match(/TitanSidebarLayout\?\.dispose\(\)/g)||[]).length,2);
console.log('Shared sidebars: independent owner/workspace preferences, bounded pointer and keyboard resizing, right inspector, mobile/detail modes, Docker rerender, file manager isolation and complete cleanup passed.');
