'use strict';
const assert=require('node:assert/strict'),explorer=require('../titan/web/file_browser.js'),{fixture,Element}=require('./desktop_test_dom.cjs');
// Match native signal/capture behavior while retaining deterministic pointer timers.
const add=Element.prototype.addEventListener;
Element.prototype.addEventListener=function(type,fn,options=false){const capture=typeof options==='object'?!!options.capture:options;add.call(this,type,fn,capture);options?.signal?.addEventListener('abort',()=>this.removeEventListener(type,fn,capture),{once:true});};
Element.prototype.click=function(){this.ownerDocument.dispatch(this,'click',{stopPropagation(){this.stopped=true;}});};
function mounted(extra={}){
 const f=fixture(),actions=[],uploads=[],clips=[],batches=[],notices=[],entries=[{name:'Grüße.txt',size:5,mutable:true,readable:true},{name:'Archive',directory:true,mutable:true,readable:true},{name:'locked',mutable:false,readable:false}];
 const ctx={entries,owner:'alice',share:'private',path:'folder',writable:true,admin:true,shares:[],targets:[],actions:Object.fromEntries(['file-preview','file-edit','file-rename','file-delete','file-trash','folder-open','folder-create','file-create','refresh'].map(action=>[action,target=>actions.push({action,...target.dataset})])),uploadFiles:(files,target)=>uploads.push({files,target}),fileClipboard:op=>clips.push(op),fileBatch:op=>batches.push(op),selectedCount:()=>1,canPaste:()=>false,toast:message=>notices.push(message),fetch:async()=>({ok:false,status:403}),...extra};
 f.surface.innerHTML=explorer.render(ctx);const browser=f.surface.querySelector('[data-file-browser]');for(const checkbox of browser.querySelectorAll('[data-file-select]'))checkbox.remove();const instance=explorer.mount(f.surface,ctx);
 const dispatch=(target,type,data={})=>f.doc.dispatch(target,type,{stopPropagation(){this.stopped=true;},...data});return {...f,actions,uploads,clips,batches,notices,ctx,browser,instance,dispatch,rows:browser.querySelectorAll('[data-fb-index]').sort((a,b)=>Number(a.dataset.fbIndex)-Number(b.dataset.fbIndex)),list:browser.querySelector('.fb-list'),menu:()=>f.doc.querySelector('.fb-context-menu'),key:key=>dispatch(f.doc.activeElement||browser,'keydown',{key}),turn:()=>new Promise(resolve=>setImmediate(resolve))};
}
(async()=>{
 let f=mounted({targets:[{name:'private',label:'Privat'}]});
 try{
  assert.equal(f.browser.dataset.inspector,'false','Inspector starts hidden so an empty side panel wastes no room');
  const event=f.dispatch(f.rows[0],'contextmenu',{clientX:995,clientY:795});assert(event.defaultPrevented);let menu=f.menu();assert(menu);assert.equal(menu.getAttribute('role'),'menu');assert(menu.querySelector('[data-action="file-rename"]'));assert(menu.querySelector('[data-action="file-delete"]'));assert(menu.querySelector('[data-fb-context="copy"]'));assert(!menu.querySelector('[data-action="file-transfer"]'),'Clipboard supplies the only copy/cut actions in the context menu');assert.equal(f.actions.length,0);
  assert(parseFloat(menu.style.left)<995&&parseFloat(menu.style.top)<795,'Menu stays in the viewport');const first=f.doc.activeElement;f.key('End');assert.notEqual(f.doc.activeElement,first);f.key('Home');assert.equal(f.doc.activeElement,first);f.key('Escape');assert.equal(f.menu(),null);assert.equal(f.doc.activeElement,f.rows[0],'Escape restores the entry focus');
  f.dispatch(f.rows[0],'contextmenu');f.dispatch(f.menu().querySelector('[data-action="file-rename"]'),'click');assert.equal(f.menu(),null);assert.deepEqual(f.actions.at(-1),{action:'file-rename',path:'folder/Grüße.txt',share:'private'});
  f.dispatch(f.rows[0],'contextmenu');f.dispatch(f.menu().querySelector('[data-fb-context="copy"]'),'click');assert.deepEqual(f.clips,['copy']);
  f.dispatch(f.rows[0],'contextmenu');f.dispatch(f.menu().querySelector('[data-fb-context="properties"]'),'click');assert.equal(f.browser.dataset.inspector,'true');assert.equal(f.browser.querySelector('[data-fb-inspector]').getAttribute('aria-pressed'),'true');
  f.dispatch(f.rows[2],'contextmenu');assert(!f.menu().querySelector('[data-action="file-delete"]'));assert(!f.menu().querySelector('[data-action="file-edit"]'));assert(f.menu().querySelector('[data-fb-context="copy"]').disabled);f.key('Escape');
  f.dispatch(f.list,'contextmenu');menu=f.menu();assert(menu.querySelector('[data-fb-context="upload"]'));assert(menu.querySelector('[data-fb-context="paste"]').disabled);f.dispatch(menu.querySelector('[data-fb-context="folder-create"]'),'click');assert.equal(f.actions.at(-1).action,'folder-create');
  // Native text input menus are left available, including copy and paste.
  assert(!f.dispatch(f.browser.querySelector('#fb-search'),'contextmenu').defaultPrevented);assert.equal(f.menu(),null);
  // Long press opens the same actionable menu; scrolling, release, or cancel abort it.
  f.dispatch(f.rows[0],'pointerdown',{pointerType:'touch'});f.advance(549);assert.equal(f.menu(),null);f.advance(1);assert(f.menu());f.dispatch(f.doc.body,'pointerdown');assert.equal(f.menu(),null);
  f.dispatch(f.rows[0],'pointerdown',{pointerType:'touch'});f.dispatch(f.rows[0],'pointermove',{pointerType:'touch',clientX:60});f.advance(600);assert.equal(f.menu(),null);
  f.dispatch(f.rows[0],'pointerdown',{pointerType:'pen'});f.dispatch(f.rows[0],'pointercancel');f.advance(600);assert.equal(f.menu(),null);
  // Dropped files retain the destination selected at the drop, and never
  // trigger the browser's default navigation to a local file.
  const files=[{name:'one.txt'},{name:'two.png'}],transfer={types:['Files'],files,items:[{kind:'file'}]};let drop=f.dispatch(f.list,'dragenter',{dataTransfer:transfer});assert(drop.defaultPrevented);assert.equal(transfer.dropEffect,'copy');assert.equal(f.browser.dataset.drop,'true');assert(!f.browser.querySelector('[data-fb-drop-zone]').hidden);
  f.dispatch(f.rows[0],'dragenter',{dataTransfer:transfer});f.dispatch(f.rows[0],'dragleave',{dataTransfer:transfer});assert.equal(f.browser.dataset.drop,'true','Leaving a nested row must not flicker the drop target');
  drop=f.dispatch(f.list,'drop',{dataTransfer:transfer});assert(drop.defaultPrevented);assert.equal(f.browser.dataset.drop,'false');assert(f.browser.querySelector('[data-fb-drop-zone]').hidden);assert.equal(f.uploads.length,1);assert.deepEqual(f.uploads[0],{files,target:{share:'private',path:'folder'}});
  const folderTransfer={types:['Files'],files:[{name:'folder'}],items:[{kind:'file',webkitGetAsEntry:()=>({isDirectory:true})}]};f.dispatch(f.list,'drop',{dataTransfer:folderTransfer});assert.equal(f.uploads.length,1);assert.match(f.notices.at(-1),/Ordner-Uploads/);
  assert(!f.dispatch(f.list,'dragover',{dataTransfer:{types:['text/plain'],items:[]}}).defaultPrevented,'Ordinary text dragging is left alone');
  f.dispatch(f.rows[0],'contextmenu');assert(f.menu());f.instance.dispose();assert.equal(f.menu(),null);assert.equal(f.browser.dataset.drop,'false');assert([...f.doc.events.values()].every(events=>events.length===0),'All document listeners are removed');
 }finally{explorer.dispose();}
 f=mounted({writable:false});try{f.dispatch(f.list,'contextmenu');assert(!f.menu().querySelector('[data-fb-context="upload"]'));const transfer={types:['Files'],files:[{name:'blocked'}],items:[]};f.dispatch(f.list,'dragover',{dataTransfer:transfer});assert.equal(transfer.dropEffect,'none');assert.match(f.browser.querySelector('[data-fb-drop-zone]').querySelector('strong').textContent,/schreibgeschützt/);assert(f.dispatch(f.list,'drop',{dataTransfer:transfer}).defaultPrevented);assert.equal(f.uploads.length,0);assert.match(f.notices.at(-1),/keine Dateien/);}finally{explorer.dispose();}
 f=mounted({selectedCount:()=>2});try{f.dispatch(f.rows[0],'contextmenu');assert(!f.menu().querySelector('[data-action="file-rename"]'));f.dispatch(f.menu().querySelector('[data-fb-context="batch-trash"]'),'click');assert.deepEqual(f.batches,['trash']);}finally{explorer.dispose();}
 f=mounted({fileClipboard:null,targets:[{name:'private'}]});try{f.dispatch(f.rows[0],'contextmenu');assert(!f.menu().querySelector('[data-fb-context="copy"]'));assert(f.menu().querySelector('[data-action="file-transfer"]'),'The existing transfer dialog is the fallback when clipboard commands are unavailable');}finally{explorer.dispose();}
 console.log('File manager: real context menu actions and permissions, focus/keyboard/clamping, touch long press/cancel, optional details, nested drag/drop, read-only and directory rejection, selection and teardown passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
