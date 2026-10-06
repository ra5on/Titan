'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const browser={},timers=[];
const context={window:browser,URL,console,FormData,setTimeout,setInterval:fn=>{timers.push(fn);return 1;},clearInterval(){}};
vm.runInNewContext(fs.readFileSync('titan/web/app_networks.js','utf8'),context);
const ui=browser.TitanNetworks;
const normalize=value=>JSON.parse(JSON.stringify(value));
async function main(){
 const listeners=new Map(),status={textContent:''};let markup='',network=null,confirmed=false,dialogHandler,actions=[];
 const root={contains:()=>true,querySelector:selector=>selector==='[data-network-manager]'?widget:status,querySelectorAll:()=>[],addEventListener:(type,fn)=>listeners.set(type,fn),removeEventListener:(type,fn)=>{if(listeners.get(type)===fn)listeners.delete(type);}};
 const widget={parentElement:root,querySelector:()=>status,set outerHTML(value){markup=value;}};
 const inventory=()=>({available:true,networks:network?[network]:[]});
 const ctx={api:async path=>{assert.equal(path,'/api/app-networks');return inventory();},action:async(operation,args,options)=>{actions.push({operation,args:normalize(args),options});assert.equal(options.wait,true);if(operation==='app_network_create'){network={name:args.name,driver:'bridge',managed:true,removable:true,subnets:[{subnet:'172.30.0.0/24',gateway:'172.30.0.1'}],containers:[],used_by:[]};return {ok:true,network};}assert.equal(operation,'app_network_remove');network=null;return {ok:true};},dialog(title,html,handler){assert.equal(title,'Netzwerk erstellen');assert.match(html,/data-network-name[^>]*required/);dialogHandler=handler;},askYesNo:async text=>{assert.match(text,/ungenutzte Netzwerk/);return confirmed;},toast(message){throw Error('Unexpected error: '+message);}};
 ui.mountInventory(root,inventory(),ctx);
 const click=async(op,name)=>{const control={dataset:{networkAction:op,name},disabled:false};await listeners.get('click')({target:{closest:()=>control}});};
 await click('create');assert(dialogHandler);const form=new FormData();form.set('name','my-apps');await dialogHandler(form);
 assert.deepEqual(actions[0].args,{name:'my-apps',internal:false});assert.match(markup,/my-apps/);assert.match(markup,/Gateway 172\.30\.0\.1/);
 await click('remove','my-apps');assert.equal(actions.length,1,'Nein must not submit a removal');
 confirmed=true;await click('remove','my-apps');assert.equal(actions.length,2);assert.deepEqual(actions[1].args,{name:'my-apps',confirmation:'my-apps'});assert.doesNotMatch(markup,/>my-apps</);
 ui.disposeWithin(root);assert.equal(listeners.size,0,'Navigation disposes inventory listeners');
 console.log('Docker network controls: direct create, automatic defaults, selected details, Ja/Nein removal, awaited jobs, refresh and disposal passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
