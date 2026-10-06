'use strict';
const assert=require('node:assert/strict'),ui=require('../titan/web/file_layout.js');
const saved=new Map(),storage={getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value)};
global.localStorage=storage;
ui.save('alice',{side:'right',width:280,collapsed:true});
assert.deepEqual(ui.load('alice'),{side:'right',width:280,collapsed:true});assert.equal(ui.load('bob').side,'left');
saved.set('titan-file-layout:bad','{oops');assert.equal(ui.load('bad').width,208);
assert.deepEqual(ui.load('blocked',{getItem(){throw Error('denied');}}),{side:'left',width:208,collapsed:false});
assert.equal(ui.normalize({side:'<script>',width:NaN}).side,'left');
class Node{
 constructor(dataset={}){this.dataset=dataset;this.events=new Map();this.attrs={};this.focused=false;this.classList={add:name=>this.classes.add(name),remove:name=>this.classes.delete(name)};this.classes=new Set();}
 addEventListener(type,fn,opts={}){const set=this.events.get(type)||new Set();set.add(fn);this.events.set(type,set);opts.signal?.addEventListener('abort',()=>set.delete(fn),{once:true});}
 fire(type,event={}){event.preventDefault??=()=>event.prevented=true;for(const fn of this.events.get(type)||[])fn(event);return event;}
 setAttribute(key,value){this.attrs[key]=value;}getAttribute(key){return this.attrs[key]??null;}hasAttribute(key){return key in this.attrs;}
 closest(){return this;}focus(){this.focused=true;}setPointerCapture(id){this.captured=id;}releasePointerCapture(id){this.released=id;}
}
const browser=new Node(),doc=new Node(),grip=new Node(),left=new Node({fbSidebarSide:'left'}),right=new Node({fbSidebarSide:'right'}),toggle=new Node(),places=new Node(),close=new Node();
toggle.attrs['data-fb-sidebar-toggle']='';close.attrs['data-fb-places-close']='';
browser.clientWidth=1100;const css={};browser.style={setProperty:(key,value)=>css[key]=value};
let mobile=false,resize,raf=[];doc.defaultView={matchMedia:()=>({matches:mobile}),ResizeObserver:class{constructor(fn){resize=fn;}observe(){}disconnect(){resize=null;}},requestAnimationFrame:fn=>(raf.push(fn),raf.length),cancelAnimationFrame:()=>raf=[]};browser.ownerDocument=doc;
browser.querySelector=selector=>selector==='[data-fb-splitter]'?grip:selector==='[data-fb-places]'?places:null;
browser.querySelectorAll=selector=>selector==='[data-fb-sidebar-side]'?[left,right]:selector==='[data-fb-sidebar-toggle]'?[toggle]:[];
const cleanup=ui.mount(browser,{owner:'bob'});
assert.equal(browser.dataset.sidebarSide,'left');assert.equal(css['--fb-sidebar-width'],'208px');
// One frame per gesture; only the final width is persisted. Capture keeps drag alive outside the handle.
grip.fire('pointerdown',{button:0,pointerId:7,clientX:208});
grip.fire('pointermove',{pointerId:7,clientX:278});grip.fire('pointermove',{pointerId:7,clientX:308});assert.equal(raf.length,1);raf.shift()();
assert.equal(css['--fb-sidebar-width'],'308px');grip.fire('pointerup',{pointerId:7});assert.equal(ui.load('bob').width,308);assert.equal(grip.released,7);
browser.fire('click',{target:right});assert.equal(browser.dataset.sidebarSide,'right');
grip.fire('pointerdown',{button:0,pointerId:8,clientX:800});grip.fire('pointermove',{pointerId:8,clientX:850});grip.fire('pointerup',{pointerId:8});assert.equal(ui.load('bob').width,258);
assert(grip.fire('keydown',{key:'ArrowLeft'}).prevented);assert.equal(ui.load('bob').width,274);
grip.fire('keydown',{key:'End'});assert.equal(ui.load('bob').width,360);
browser.clientWidth=580;resize();assert.equal(css['--fb-sidebar-width'],'260px');assert.equal(ui.load('bob').width,360);browser.clientWidth=1100;resize();assert.equal(css['--fb-sidebar-width'],'360px');
browser.fire('click',{target:toggle});assert.equal(browser.dataset.sidebarCollapsed,'true');assert.equal(toggle.attrs['aria-expanded'],'false');browser.fire('click',{target:toggle});assert.equal(browser.dataset.sidebarCollapsed,'false');
mobile=true;grip.fire('pointerdown',{button:0,pointerId:9,clientX:200});assert.equal(grip.captured,8);
browser.dataset.places='true';doc.fire('keydown',{key:'Escape'});assert.equal(browser.dataset.places,'false');assert(places.focused);
grip.fire('dblclick');assert.equal(ui.load('bob').width,208);
cleanup();assert.equal(resize,null);for(const node of [browser,doc,grip])for(const listeners of node.events.values())assert.equal(listeners.size,0);
delete global.localStorage;
console.log('File sidebar: per-user persistence, captured/coalesced drag, both sides, keyboard resize, viewport clamp, collapse, mobile close and cleanup passed.');
