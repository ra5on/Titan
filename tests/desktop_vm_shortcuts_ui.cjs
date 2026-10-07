'use strict';
const assert=require('node:assert/strict'),ui=require('../titan/web/desktop_shortcuts.js'),{fixture}=require('./desktop_test_dom.cjs');
(async()=>{
 const f=fixture(),id='12345678-1234-1234-1234-123456789abc',key='vm:'+id,writes=[],opened=[];
 const api=async(path,body)=>{if(path==='/api/vms')return {vms:[{id,name:'windows-internal',display_name:'Windows 11'}]};if(path==='/api/apps')return {installed:[]};if(body){writes.push(body);return body;}return {version:2,items:['tool:terminal'],positions:{}};};
 const desk=await ui.mount(f.surface,{tools:[['terminal','Terminal',''],['vms','VMs','']],user:{role:'admin'},icon:()=>'',esc:String,api,toast(){},open:hash=>opened.push(hash),menu(){}});
 try{assert(desk.add(key));assert(!desk.add('vm:../foreign'));const icon=f.surface.querySelector(`[data-shortcut-open="${key}"]`);assert.match(icon.textContent,/Windows 11/);f.doc.dispatch(icon,'click');assert.equal(opened.at(-1),'#vms?vm='+id+'&tab=console');assert(writes.some(row=>row.items.includes(key)));await desk.refreshVMs();assert(desk.entries().some(([entry])=>entry===key));assert.equal(ui.normalize({version:2,items:[key]},[]).items[0],key);}finally{desk.destroy();}
 console.log('VM desktop shortcuts: canonical identity, display label, persistence and console deep-link passed.');
})();
