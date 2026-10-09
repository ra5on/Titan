'use strict';
const assert=require('node:assert/strict');
const ui=require('../titan/web/desktop_shortcuts.js');
const {fixture}=require('./desktop_test_dom.cjs');
(async()=>{
 const f=fixture(),pending=new Map();
 const api=path=>path==='/api/launcher-layout'?Promise.resolve({version:2,items:['tool:files']}):new Promise(resolve=>pending.set(path,resolve));
 const desk=await Promise.race([
  ui.mount(f.surface,{tools:[['files','Dateien','']],user:{role:'admin'},icon:()=>'',esc:String,api,toast(){},open(){},menu(){}}),
  new Promise((_,reject)=>{const timer=setTimeout(()=>reject(Error('Slow host discovery blocked desktop startup')),1000);timer.unref();})
 ]);
 try{
  assert(f.surface.querySelector('[data-shortcut-open="tool:files"]'));
  assert(pending.has('/api/apps'));assert(pending.has('/api/vms'));
  const id='12345678-1234-1234-1234-123456789abc';
  pending.get('/api/apps')({installed:[]});pending.get('/api/vms')({vms:[{id,name:'test',display_name:'Test VM'}]});
  await new Promise(resolve=>setImmediate(resolve));
  assert(desk.entries().some(([key])=>key==='vm:'+id));
 }finally{desk.destroy();}
 console.log('Desktop renders while Docker and VM discovery are pending; delayed VM data becomes available.');
})().catch(error=>{console.error(error);process.exitCode=1;});
