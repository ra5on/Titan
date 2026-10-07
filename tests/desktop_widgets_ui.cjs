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

async function mounted(role,preferences,{acceptSave=true}={}){
 const f=fixture(),saved=[],opened=[],requests=[],toggle=f.doc.createElement('button');toggle.setAttribute('id','widgets-toggle');f.doc.body.append(toggle);
 const widget=ui.mount({doc:f.doc,user:{role},api:async path=>{requests.push(path);return {cpu_percent:20,memory_total:100,memory_occupied:40};},esc:String,bytes:String,preferences,save:value=>{saved.push(value);return acceptSave;},open:value=>opened.push(value),jobs(){}});
 await new Promise(resolve=>setImmediate(resolve));return {...f,widget,saved,opened,requests,toggle,card:key=>f.doc.querySelector('[data-widget-card="'+key+'"]'),gallery:()=>f.doc.querySelector('.widget-gallery')};
}
(async()=>{
 let f=await mounted('admin',{visible:false,collapsed:true,items:['cpu','health'],positions:{cpu:{x:100,y:300}}});
 try{
  assert.equal(f.doc.querySelectorAll('[data-widget-card]').length,0);assert.equal(f.requests.length,0);
  f.doc.dispatch(f.toggle,'click');let gallery=f.gallery();assert(gallery.open,'The topbar opens the picker even while every widget is hidden');assert.equal(gallery.querySelectorAll('[data-widget-choice]').length,6);assert.equal(gallery.querySelector('[data-widget-choice="cpu"]').dataset.selected,'true','Existing selection is visible in the gallery');
  f.doc.dispatch(gallery.querySelector('[data-widget-add="ram"]'),'click');await new Promise(resolve=>setImmediate(resolve));assert.equal(f.doc.querySelectorAll('[data-widget-card]').length,3,'Adding creates independent actual desktop cards');assert.equal(f.saved.at(-1).visible,true);assert.equal(f.saved.at(-1).collapsed,false);assert.deepEqual(f.saved.at(-1).items,['cpu','health','ram']);assert(f.requests.includes('/api/status'));
  let cpu=f.card('cpu'),ram=f.card('ram'),handle=cpu.querySelector('[data-widget-move]');const ramBefore=ram.getBoundingClientRect();
  f.doc.dispatch(handle,'pointerdown',{pointerType:'touch'});f.doc.dispatch(handle,'pointermove',{pointerType:'touch',clientX:340,clientY:310});f.doc.dispatch(handle,'pointerup',{pointerType:'touch',clientX:340,clientY:310});assert(f.saved.at(-1).positions.cpu);assert.equal(f.saved.at(-1).positions.ram,undefined,'Moving CPU never overwrites RAM position');assert.deepEqual(f.card('ram').getBoundingClientRect(),ramBefore);
  const before={...f.saved.at(-1).positions.cpu},saveCount=f.saved.length;cpu=f.card('cpu');handle=cpu.querySelector('[data-widget-move]');f.doc.dispatch(handle,'pointerdown');f.doc.dispatch(handle,'pointermove',{clientX:500,clientY:600});f.doc.dispatch(handle,'pointercancel');assert.equal(f.saved.length,saveCount);const afterCancel=f.card('cpu').getBoundingClientRect(),point=ui.placement(before,{left:8,top:68,width:884,height:634},272,260);assert.equal(afterCancel.left,point.left);assert.equal(afterCancel.top,point.top);
  handle=f.card('cpu').querySelector('[data-widget-move]');f.doc.dispatch(handle,'keydown',{key:'ArrowLeft'});assert(f.saved.at(-1).positions.cpu.x<before.x);assert.equal(f.doc.activeElement,f.card('cpu').querySelector('[data-widget-move]'));
  const metric=f.card('cpu').querySelector('[data-widget-open]'),count=f.saved.length;f.doc.dispatch(metric,'pointerdown');f.doc.dispatch(metric,'pointermove',{clientX:400});f.doc.dispatch(metric,'pointerup');assert.equal(f.saved.length,count,'Metrics controls never start a drag');f.doc.dispatch(metric,'click');assert.equal(f.opened[0],'#resources');
  f.doc.dispatch(gallery.querySelector('[data-widget-remove="cpu"]'),'click');assert(!f.card('cpu'));assert(!f.saved.at(-1).positions?.cpu);assert(f.card('ram'));
  f.doc.dispatch(gallery.querySelector('[data-widget-hide]'),'click');assert(!gallery.open);assert.equal(f.doc.querySelectorAll('[data-widget-card]').length,0);assert.equal(f.doc.activeElement,f.toggle);
  const entry=f.doc.createElement('button');entry.setAttribute('data-widgets-picker','');f.doc.body.append(entry);f.doc.dispatch(entry,'click');assert(gallery.open,'Visible main/account/desktop entries open the same gallery');f.doc.dispatch(gallery.querySelector('[data-widget-add="health"]'),'click');assert(f.card('health'));
  f.surface._rect={left:0,top:60,width:390,height:310,right:390,bottom:370};for(const listener of f.win.events.get('resize'))listener.fn();for(const card of f.doc.querySelectorAll('[data-widget-card]')){const rect=card.getBoundingClientRect();assert(rect.left>=8&&rect.right<=382&&rect.top>=68&&rect.bottom<=362,'Each card remains in the resized viewport');}
 }finally{f.widget.destroy();}
 assert.equal(f.doc.querySelector('.desktop-widget'),null);assert([...f.doc.events.values()].every(events=>events.length===0));
 f=await mounted('user',{visible:false,items:['cpu','health','clock']});
 try{
  f.widget.openPicker(f.toggle);assert.equal(f.gallery().querySelectorAll('[data-widget-choice]').length,1);assert.equal(f.gallery().querySelector('[data-widget-choice]').dataset.widgetChoice,'clock');f.doc.dispatch(f.gallery().querySelector('[data-widget-add="clock"]'),'click');assert(f.card('clock'));assert.equal(f.requests.length,0,'Regular users never request administrator metrics');f.widget.updateAlerts([{severity:'error'}]);f.widget.updateJobs([{status:'running'}]);assert(!f.card('notifications'));assert(!f.card('activity'));
  f.doc.dispatch(f.gallery().querySelector('[data-widget-remove="clock"]'),'click');assert.equal(f.doc.querySelectorAll('[data-widget-card]').length,0);assert.deepEqual(f.saved.at(-1).items,[]);f.widget.openPicker();assert.equal(f.gallery().querySelectorAll('[data-widget-choice]').length,1,'An explicitly empty desktop can always add a widget again');
 }finally{f.widget.destroy();}
 f=await mounted('user',{visible:true,items:['cpu','ram','health']});try{assert(f.card('clock'),'Legacy administrator defaults become the safe clock for a regular account');assert.equal(f.requests.length,0);}finally{f.widget.destroy();}
 f=await mounted('user',{visible:true,items:[]});try{assert.equal(f.doc.querySelectorAll('[data-widget-card]').length,0,'Intentionally empty selection remains empty');assert.equal(f.requests.length,0);}finally{f.widget.destroy();}
 f=await mounted('user',{visible:true,items:['clock']});try{assert(f.card('clock').getBoundingClientRect().top>=190,'New cards start below the first application icon row');}finally{f.widget.destroy();}
 f=await mounted('user',{visible:true,items:['clock'],positions:{clock:{x:1000,y:0}}});try{assert.equal(f.card('clock').getBoundingClientRect().top,68,'Explicit user positions retain the entire available area');}finally{f.widget.destroy();}
 for(const preferences of [{visible:true,items:['clock']},{visible:true,items:['clock'],positions:{clock:{x:250,y:100}}}]){
  f=await mounted('user',preferences,{acceptSave:false});try{const before=f.card('clock').getBoundingClientRect(),handle=f.card('clock').querySelector('[data-widget-move]');f.doc.dispatch(handle,'pointerdown');f.doc.dispatch(handle,'pointermove',{clientX:300,clientY:400});f.doc.dispatch(handle,'pointerup');assert.equal(f.saved.length,1);assert.deepEqual(f.card('clock').getBoundingClientRect(),before,'A rejected drag save restores the previous placement, including an unsaved default');}finally{f.widget.destroy();}
 }
 console.log('Desktop widget gallery: hidden/collapsed entry points, visible selection, actual independent cards, add/remove, per-card drag and keyboard, cancellation, resize, cleanup and regular-user metric isolation passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
