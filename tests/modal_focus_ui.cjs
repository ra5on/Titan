'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();function node(selector){if(!nodes.has(selector))nodes.set(selector,{listeners:{},innerHTML:'',open:false,isConnected:true,addEventListener(type,fn){this.listeners[type]=fn;},showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();},focus(){this.focused=true;}});return nodes.get(selector);}
let replacements=[];const document={activeElement:null,querySelector:node,querySelectorAll:()=>replacements,addEventListener(){}};
const context={document,window:{addEventListener(){}},location:{hash:'#services'},setInterval:()=>0,setTimeout:()=>0,clearInterval(){},URLSearchParams,console};vm.createContext(context);vm.runInContext(fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,''),context);const evaluate=expr=>vm.runInContext(expr,context);
node('#dialog').scrollTop=400;
evaluate("dialog('Neue Ansicht','<p>Start</p>')");
assert.equal(node('#dialog').scrollTop,0,'A new dialog starts at its title after an earlier long form');
node('#dialog').close();
const opener={dataset:{service:'docker.service',serviceAction:'details'},isConnected:true,focus(){this.focused=true;}};document.activeElement=opener;evaluate("dialog('Docker','<p>Logs</p>')");document.activeElement={dataset:{action:'close'}};evaluate("dialog('Docker','<p>Aktualisiert</p>')");node('#dialog').close();assert(opener.focused,'Refreshing a modal retains its original trigger');
opener.focused=false;document.activeElement=opener;evaluate("dialog('Docker','<p>Logs</p>')");opener.isConnected=false;const replacement={dataset:{service:'docker.service',serviceAction:'details'},focus(){this.focused=true;}};replacements=[replacement];node('#dialog').close();assert(replacement.focused,'Re-rendered service row is found by semantic identity');
document.activeElement={dataset:{action:'app-install',id:'nextcloud'},isConnected:false};evaluate("dialog('App','<p>Details</p>')");replacements=[];node('#dialog').close();assert(node('#main').focused,'Main remains a predictable fallback after the originating action disappears');
console.log('Modal focus: original trigger preserved through refresh, matching re-rendered service trigger and main fallback passed.');
