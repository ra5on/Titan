'use strict';
const assert=require('node:assert/strict'),ui=require('../titan/web/desktop_shortcuts.js');
const allowed=['tool:files','tool:settings','tool:apps','tool:storage','tool:vms'];
assert.equal(ui.normalize({},allowed).items.length,4);
assert.deepEqual(ui.normalize({version:2,items:[]},allowed).items,[],'An intentionally empty desktop remains empty');
const legacy=ui.normalize({items:['tool:files','tool:files','javascript:x','tool:root','app:demo'],hidden:['tool:files']},allowed);
assert.deepEqual(legacy.items,['app:demo']);
const grouped=ui.group(['tool:files','tool:vms'],'tool:files','tool:vms');assert.equal(grouped.length,1);assert.deepEqual(grouped[0].items,['tool:vms','tool:files']);
assert.deepEqual(ui.remove(grouped,'tool:files')[0].items,['tool:vms']);assert.equal(grouped[0].items.length,2,'Removing a shortcut must not mutate previous state');
const arranged=ui.place(['a','b','c'],{a:{x:20,y:30},b:{x:20,y:30}},2,2);assert.equal(new Set(Object.values(arranged).map(p=>p.x+','+p.y)).size,3);assert(Object.values(arranged).every(p=>p.x<2));
assert.equal(ui.safeUrl('javascript:alert(1)'), '');assert.equal(ui.safeUrl('https://user:pass@nas/'),'');assert.equal(ui.safeUrl('http://nas:8096'),'http://nas:8096/');
const reloaded=ui.normalize({version:2,items:grouped,positions:{[grouped[0].id]:{x:4,y:2}},widgets:{visible:false,collapsed:true,items:['ram']}},allowed);assert.equal(reloaded.positions[grouped[0].id].x,4);assert.equal(reloaded.widgets.visible,false);
assert.deepEqual(ui.normalize({desktop:{background_click:'minimize',transparency:100}},allowed).desktop,{background_click:'minimize',dock_auto_hide:false,transparency:100,color_mode:'dark'});
assert.deepEqual(ui.normalize({desktop:{background_click:'invalid',transparency:'80'}},allowed).desktop,{background_click:'none',dock_auto_hide:false,transparency:40,color_mode:'dark'});
console.log('Desktop shortcuts: defaults, empty persistence, migration, folders, removal, collision-free mobile placement and safe app URLs passed.');

// Exercise the shared write queue: changing desktop appearance must retain widgets
// and icon placement even when their edits happen during an outstanding request.
class Element{
 constructor(){this.dataset={};this.style={};this.clientWidth=900;this.clientHeight=700;this.events={};}
 setAttribute(){} querySelectorAll(){return [];} querySelector(){return null;}
 contains(){return false;} append(){} remove(){}
 addEventListener(type,fn){this.events[type]=fn;} removeEventListener(type){delete this.events[type];}
}
async function mounted(api){const surface=new Element(),doc=new Element();doc.body=new Element();doc.defaultView={ResizeObserver:class{observe(){} disconnect(){}}};doc.createElement=()=>new Element();surface.ownerDocument=doc;return ui.mount(surface,{tools:[['files','Files',''],['settings','Settings','']],user:{name:'alice',role:'admin'},icon:()=>'',esc:String,api,toast:()=>{},open(){},menu(){}});}
(async()=>{
 const writes=[];let release;
 const desk=await mounted(async(path,value)=>{if(path==='/api/apps')return {installed:[]};if(!value)return {version:2,items:['tool:files'],positions:{'tool:files':{x:2,y:3}},icon_size:'large',widgets:{visible:true,collapsed:false,items:['cpu']},desktop:{background_click:'none',transparency:30,color_mode:'dark'}};writes.push(value);if(writes.length===1)await new Promise(resolve=>release=resolve);return value;});
 assert.equal(desk.desktop().transparency,30);assert(desk.setDesktop({transparency:70,background_click:'minimize'}));
 desk.setWidgets({visible:false,collapsed:true,items:['ram']});desk.add('tool:settings');assert.equal(writes.length,1,'Concurrent edits use one active save');
 release();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(writes.length,2);assert.deepEqual(writes[1].desktop,{transparency:70,background_click:'minimize',dock_auto_hide:false,color_mode:'dark'});assert.deepEqual(writes[1].widgets,{visible:false,collapsed:true,items:['ram']});assert.deepEqual(writes[1].positions,{'tool:files':{x:2,y:3}});assert.equal(writes[1].icon_size,'large');assert.deepEqual(writes[1].items,['tool:files','tool:settings']);desk.destroy();
 let rejectedWrites=0;const readonly=await mounted(async(path,value)=>{if(path==='/api/apps')return {installed:[]};if(value)rejectedWrites++;throw Error('offline');});assert.equal(readonly.desktopWritable(),false);assert.equal(readonly.setDesktop({transparency:80}),false);assert.equal(rejectedWrites,0);readonly.destroy();
 console.log('Desktop appearance: serialized shared saves preserve shortcuts, positions, icon size and widgets; failed loads remain read-only.');
})().catch(error=>{console.error(error);process.exitCode=1;});
