'use strict';
const assert=require('node:assert/strict'),ui=require('../titan/web/desktop_widgets.js');
const {fixture}=require('./desktop_test_dom.cjs');
assert.equal(ui.metrics({cpu_percent:0,memory_total:100,memory_used:10,memory_occupied:80}).ram,80);assert.equal(ui.metrics({cpu_percent:0}).cpu,0);
for(const value of [null,undefined,NaN,'50',-1,101])assert.equal(ui.metrics({cpu_percent:value}).cpu,null);
assert.equal(ui.metrics({memory_total:100,memory_occupied:101}).ram,null);
assert.deepEqual(ui.normalize({items:['ram','ram','bogus'],visible:false}),{items:['ram'],visible:false,collapsed:false});
assert.equal(ui.health(null),'Wird geladen');assert.equal(ui.health({service_details:{docker:{relevant:false,installed:false,active:false}}}),'Verbunden');
assert.equal(ui.health({service_details:{docker:{relevant:true,installed:false,active:false}}}),'Dienste prüfen');assert.equal(ui.health({telemetry_errors:{cpu:'offline'}}),'Messhinweise vorhanden');
assert.deepEqual(ui.normalize({position:{x:250,y:1000}}).position,{x:250,y:1000});
for(const position of [{x:-1,y:0},{x:1001,y:0},{x:0.5,y:0},{x:'30',y:0}])assert.equal(ui.normalize({position}).position,undefined);
const area={left:20,top:60,width:1000,height:700};
assert.deepEqual(ui.placement(undefined,area,272,260),{left:748,top:60});
assert.deepEqual(ui.coordinates(-50,2000,area,272,260),{x:0,y:1000});
assert.deepEqual(ui.coordinates(500,500,area,2000,2000),{x:0,y:0});
const normalized=ui.coordinates(250,210,area,272,260),roundtrip=ui.placement(normalized,area,272,260);assert(Math.abs(roundtrip.left-250)<1&&Math.abs(roundtrip.top-210)<1);
console.log('Desktop widgets: occupied RAM, unavailable values, relevant service failures and saved selection passed.');

(async()=>{
 const f=fixture(),saved=[],opened=[],toggle=f.doc.createElement('button');toggle.setAttribute('id','widgets-toggle');f.doc.body.append(toggle);
 const widget=ui.mount({doc:f.doc,user:{role:'admin'},api:async()=>({cpu_percent:20,memory_total:100,memory_occupied:40}),esc:String,bytes:String,preferences:{items:['cpu','health'],visible:true},save:value=>saved.push(value),open:value=>opened.push(value),jobs(){}});
 try{
  await new Promise(resolve=>setImmediate(resolve));const box=f.doc.querySelector('.desktop-widget');let handle=box.querySelector('[data-widget-move]');assert(handle);assert.equal(box.style.top,'68px');
  const collapse=box.querySelector('[data-widget-collapse]');f.doc.dispatch(collapse,'pointerdown');f.doc.dispatch(collapse,'pointermove',{clientX:400});f.doc.dispatch(collapse,'pointerup');assert.equal(saved.length,0,'Widget buttons must never start movement');
  f.doc.dispatch(handle,'pointerdown',{pointerType:'touch'});f.doc.dispatch(handle,'pointermove',{pointerType:'touch',clientX:-400,clientY:300});f.doc.dispatch(handle,'pointerup',{pointerType:'touch',clientX:-400,clientY:300});assert.equal(saved.length,1);assert(saved[0].position.x<1000&&saved[0].position.y>0);assert.deepEqual(saved[0].items,['cpu','health']);assert.equal(f.doc.activeElement,box.querySelector('[data-widget-move]'));
  const before={...saved.at(-1).position},saveCount=saved.length;handle=box.querySelector('[data-widget-move]');f.doc.dispatch(handle,'pointerdown');f.doc.dispatch(handle,'pointermove',{clientX:500,clientY:600});f.doc.dispatch(handle,'pointercancel');assert.equal(saved.length,saveCount);const afterCancel=box.getBoundingClientRect(),point=ui.placement(before,{left:8,top:68,width:884,height:634},272,260);assert.equal(afterCancel.left,point.left);assert.equal(afterCancel.top,point.top);
  handle=box.querySelector('[data-widget-move]');f.doc.dispatch(handle,'keydown',{key:'ArrowRight'});assert(saved.at(-1).position.x>before.x);assert.equal(f.doc.activeElement,box.querySelector('[data-widget-move]'));
  const settings=box.querySelector('[data-widget-settings]');f.doc.dispatch(settings,'click');const dialog=f.doc.querySelector('.widget-settings');assert(dialog.open);const buttons=dialog.querySelectorAll('button');assert.equal(buttons[0].getAttribute('type'),'submit');assert(buttons[1].hasAttribute('data-widget-cancel'));assert.equal(f.doc.activeElement,dialog.querySelector('input'));
  f.surface._rect={left:0,top:60,width:390,height:310,right:390,bottom:370};for(const listener of f.win.events.get('resize'))listener.fn();const resized=box.getBoundingClientRect();assert(resized.left>=8&&resized.right<=382&&resized.top>=68&&resized.bottom<=362,'Normalized placement remains visible after viewport resize');
  const metric=box.querySelector('[data-widget-open]');f.doc.dispatch(metric,'click');assert.equal(opened[0],'#resources');
 }finally{widget.destroy();}
 assert.equal(f.doc.querySelector('.desktop-widget'),null);assert([...f.doc.events.values()].every(events=>events.length===0));
 console.log('Desktop widget movement: isolated visible handle, touch drag, cancel recovery, keyboard focus, responsive position, shared preference payload and safe settings order passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
