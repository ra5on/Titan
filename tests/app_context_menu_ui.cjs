'use strict';
const assert=require('node:assert/strict'),ui=require('../titan/web/app_context_menu.js');
const control=(label,dataset={},disabled=false)=>({dataset,disabled,textContent:label,isConnected:true,classList:{contains:()=>false},getAttribute:key=>key==='aria-label'?null:key==='aria-disabled'?String(disabled):null});
const first=control('Jellyfin image with a very long name',{engineAction:'select',engineId:'one'}),duplicate=control('Details',{engineAction:'select',engineId:'one'}),stop=control('Stoppen',{engineAction:'stop',engineId:'one'}),remove=control('App entfernen',{action:'app-action',id:'one'},true);
const result=ui.commands({querySelectorAll:()=>[first,duplicate,stop,remove]});
assert.equal(result.length,3,'Identical commands appear once');assert.equal(result[0].label,'Details öffnen');assert.equal(result[0].node,first,'Commands delegate to the original guarded control');assert.equal(result[1].node,stop);assert.equal(result[2].disabled,true,'A context menu cannot enable a disabled action');assert.equal(result[2].danger,true);
assert.deepEqual(ui.commands(null),[]);assert.equal(ui.commands({querySelectorAll:()=>[control('linux',{action:'vm-console',id:'one'})]})[0].label,'Konsole öffnen');
console.log('App context actions: guarded source controls, deduplication, disabled mutation preservation, VM/Docker labels and dangerous-action indication passed.');
