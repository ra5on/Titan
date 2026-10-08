'use strict';
const assert=require('node:assert/strict'),shortcuts=require('../titan/web/desktop_shortcuts.js'),widgets=require('../titan/web/desktop_widgets.js'),{fixture}=require('./desktop_test_dom.cjs');
const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
(async()=>{
 const f=fixture(),tools=[['files','Dateien','Dateien öffnen'],['apps','App Store','Apps entdecken'],['vms','Virtuelle Maschinen','VMs öffnen']],user={name:'Anna <Admin>',role:'admin'};
 const api=async(path,value)=>value||({'/api/launcher-layout':{version:2,items:['tool:files','tool:apps','tool:vms'],positions:{}},'/api/apps':{installed:[]},'/api/vms':{vms:[]},'/api/status':{cpu_percent:12,memory_total:100,memory_occupied:31}}[path]||{});
 const desk=await shortcuts.mount(f.surface,{tools,user,api,icon:()=>'',esc:escape,toast(){},open(){},menu(){}});
 let live;
 try{
  const heading=f.surface.querySelector('.desktop-welcome h1')||f.surface.querySelector('h1');assert(heading.textContent.includes('Anna <Admin>'));assert.equal(heading.querySelector('Admin'),null,'Account labels stay text, never markup');
  const file=f.surface.querySelector('[data-shortcut="tool:files"]'),apps=f.surface.querySelector('[data-shortcut="tool:apps"]');assert.equal(file.style.top,apps.style.top,'New shortcuts form one central row');assert(parseFloat(file.style.left)>0,'The default row is centered rather than pinned to the left edge');
  live=widgets.mount({doc:f.doc,user,api,esc:escape,bytes:String,preferences:{items:['cpu','ram','health']},save:value=>desk.setWidgets(value),open(){},jobs(){}});await new Promise(resolve=>setImmediate(resolve));
  const cards=f.surface.querySelectorAll('[data-widget-card]');assert.equal(cards.length,3);assert(cards.every(card=>card.parentElement===f.surface),'Widgets share the desktop scroll surface');assert.equal(cards[0].style.top,cards[1].style.top,'Default live widgets form a centered row');assert(parseFloat(file.style.top)>=Number(f.surface.dataset.widgetDefaultBottom),'Default shortcuts begin below the actual widget row');
  const cpu=cards[0],handle=cpu.querySelector('[data-widget-move]');handle.focus();await desk.refreshApps();assert.equal(f.surface.querySelector('[data-shortcut="tool:files"]'),file,'Unchanged app polling preserves shortcut nodes');assert.equal(f.surface.querySelector('[data-widget-card="cpu"]'),cpu,'App polling never removes live widget cards');assert.equal(f.doc.activeElement,handle,'Polling preserves widget keyboard focus');
  desk.setWidgets({items:['cpu']});assert.equal(f.surface.querySelector('[data-widget-card="cpu"]'),cpu,'Saving a widget preference preserves the live desktop layer');
 }finally{live?.destroy();desk.destroy();}
 assert.equal(f.doc.querySelector('.desktop-shortcuts-layer'),null);assert.equal(f.doc.querySelector('[data-widget-card]'),null);
 console.log('Desktop composition: safe welcome text, centered defaults, one scroll surface, preserved live cards and focus, and cleanup passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
