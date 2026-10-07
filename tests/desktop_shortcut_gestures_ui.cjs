'use strict';
const assert=require('node:assert/strict'),ui=require('../titan/web/desktop_shortcuts.js'),{fixture}=require('./desktop_test_dom.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function mounted({readonly=false,role='admin',answer=true}={}){
 const f=fixture(),writes=[],actions=[],opened=[],toasts=[];let confirmations=0;
 const api=async(path,value)=>{if(path==='/api/apps')return {installed:[{id:'nextcloud',name:'Nextcloud',web_available:true,web_state:'ready',state:'running',endpoints:[{scope:'lan',url:'https://nas.test:8443'}]}]};if(value){writes.push(value);return value;}if(readonly)throw Error('offline');return {version:2,items:['tool:files','app:nextcloud'],positions:{},desktop:{color_mode:'dark'}};};
 // Simulate the workspace's existing document-capture launcher handler. The
 // long-press click guard must run before it, on the window capture phase.
 let launched=0;f.doc.addEventListener('click',event=>{if(event.target.closest('[data-menu-launch]'))launched++;},true);
 const desk=await ui.mount(f.surface,{tools:[['files','Dateien','']],user:{name:'alice',role},icon:()=>'',esc:String,api,toast:(...v)=>toasts.push(v),open:value=>opened.push(value),menu(){},action:async(...v)=>actions.push(v),confirm:async()=>{confirmations++;return answer;}});
 const dialog=f.doc.createElement('dialog');dialog.innerHTML='<div class="desktop-menu-entry"><button data-menu-launch="app:nextcloud">Nextcloud</button><button data-menu-context="app:nextcloud">⋯</button></div>';f.doc.body.append(dialog);dialog.showModal();
 return {...f,desk,writes,actions,opened,toasts,dialog,context:()=>f.doc.querySelector('.desktop-quick-actions'),launch:()=>dialog.querySelector('[data-menu-launch]'),icon:()=>f.surface.querySelector('[data-shortcut-open="app:nextcloud"]'),launched:()=>launched,confirmations:()=>confirmations};
}
(async()=>{
 const originalNow=Date.now;let f;
 try{
  f=await mounted();Date.now=f.now;
  const launch=f.launch();f.doc.dispatch(launch,'pointerdown',{pointerType:'touch'});f.advance(550);
  const menu=f.context();assert(!menu.hidden);assert.equal(menu.parentElement,f.dialog,'Menu is inside the active modal top layer');assert(menu.querySelector('[data-context="manage"]'));assert(menu.querySelector('[data-context="remove"]'));assert(menu.querySelector('[data-context="app-stop"]'),'HTTP readiness and container running state remain distinct');
  f.doc.dispatch(launch,'pointermove',{pointerType:'touch',clientX:300});assert.equal(f.surface.querySelector('.desktop-drop-preview'),null,'A held touch must never become a drag');
  f.doc.dispatch(launch,'pointerup',{pointerType:'touch'});const click=f.doc.dispatch(launch,'click');assert(click.defaultPrevented);assert.equal(f.launched(),0,'Synthetic click cannot reach the earlier workspace launcher');assert.equal(f.writes.length,0);
  f.doc.dispatch(menu.querySelector('[data-context="open"]'),'click');assert.equal(f.win.opened.length,1,'An explicit quick action still opens while pointer click is suppressed');
  f.advance(1000);const trigger=f.dialog.querySelector('[data-menu-context]');f.dialog.showModal();f.doc.dispatch(trigger,'click');assert(!menu.hidden);assert.equal(f.doc.activeElement,menu.querySelector('button'));
  f.doc.dispatch(f.doc.activeElement,'keydown',{key:'End'});assert.equal(f.doc.activeElement,menu.querySelectorAll('button').at(-1));
  f.doc.dispatch(f.doc.activeElement,'keydown',{key:'Escape'});assert(menu.hidden);assert(f.dialog.open,'Escape dismisses only quick actions');assert.equal(f.doc.activeElement,trigger);
  f.doc.dispatch(launch,'keydown',{key:'F10',shiftKey:true});assert(!menu.hidden);f.doc.dispatch(f.doc.activeElement,'keydown',{key:'Tab'});assert(menu.hidden);assert.equal(f.doc.activeElement,launch);
  f.doc.dispatch(launch,'contextmenu');f.doc.dispatch(menu.querySelector('[data-context="manage"]'),'click');assert.equal(f.opened.at(-1),'#docker?app=nextcloud');
  f.doc.dispatch(launch,'contextmenu');f.doc.dispatch(menu.querySelector('[data-context="remove"]'),'click');await flush();assert(!f.desk.contains('app:nextcloud'));assert.equal(f.actions.length,0,'Removing a shortcut never deinstalls an app');
  f.doc.dispatch(launch,'contextmenu');assert(menu.querySelector('[data-context="pin"]'));f.doc.dispatch(menu.querySelector('[data-context="pin"]'),'click');await flush();assert(f.desk.contains('app:nextcloud'));
  f.doc.dispatch(launch,'contextmenu');f.doc.dispatch(menu.querySelector('[data-context="app-remove"]'),'click');await flush();assert.equal(f.confirmations(),1);assert.equal(f.actions[0][0],'app_action');assert.deepEqual(f.actions[0][1],{app:'nextcloud',action:'remove'});assert.equal(f.actions[0][2].wait,true);f.desk.destroy();

  f=await mounted({answer:false});Date.now=f.now;const icon=f.icon();f.doc.dispatch(icon,'contextmenu');f.doc.dispatch(f.context().querySelector('[data-context="app-remove"]'),'click');await flush();assert.equal(f.actions.length,0);assert(f.desk.contains('app:nextcloud'),'Rejected confirmation retains app and shortcut');
  f.doc.dispatch(icon,'pointerdown',{pointerType:'touch'});f.doc.dispatch(icon,'pointermove',{pointerType:'touch',clientX:160});f.advance(600);assert(f.context().hidden,'Movement cancels hold timer');assert(f.surface.querySelector('.desktop-drop-preview'));f.doc.dispatch(icon,'pointerup',{clientX:160});await flush();assert(f.writes.at(-1).positions['app:nextcloud']);assert(f.doc.dispatch(f.icon(),'click').defaultPrevented,'Dragging a real anchor never opens its URL');
  f.advance(1000);const next=f.icon();next.focus();f.doc.dispatch(next,'keydown',{key:'ArrowDown',altKey:true});await flush();assert.equal(f.writes.at(-1).positions['app:nextcloud'].y,1);assert.equal(f.writes.at(-1).desktop.color_mode,'dark');
  const before=f.writes.length,more=f.surface.querySelector('[data-shortcut-more]');f.doc.dispatch(more,'pointerdown',{pointerType:'touch'});f.advance(600);assert(f.context().hidden,'Secondary controls do not start long press');assert.equal(f.writes.length,before);f.desk.destroy();

  f=await mounted({readonly:true});Date.now=f.now;f.doc.dispatch(f.launch(),'contextmenu');assert(f.context().querySelector('[data-context="pin"]').disabled);f.doc.dispatch(f.launch(),'pointerdown',{pointerType:'touch'});f.advance(550);assert(!f.context().hidden,'Read-only desktop still supports open/details');f.doc.dispatch(f.launch(),'pointerup');assert.equal(f.writes.length,0);f.desk.destroy();
  console.log('Desktop quick actions: touch hold, click-through prevention, drag cancellation, modal scope, keyboard/focus, safe app actions and persisted placement passed.');
 }finally{f?.desk.destroy();Date.now=originalNow;}
})().catch(error=>{console.error(error);process.exitCode=1;});
