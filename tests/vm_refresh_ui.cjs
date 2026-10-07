'use strict';
// Execute the real application refresh path with delayed API responses.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),manager={};
function node(selector){if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',dataset:{},attributes:{},textContent:'',classList:{add(){},remove(){},toggle(){}},setAttribute(key,value){this.attributes[key]=value;},removeAttribute(key){delete this.attributes[key];},querySelector:query=>query==='[data-manager="vms"]'?manager:null,querySelectorAll:()=>[],addEventListener(){},contains:()=>false});return nodes.get(selector);}
const browser={addEventListener(){},TitanVMExtensions:{dispose(){},selectionState:()=>null}};
const context={window:browser,document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},location:{hash:'#vms',search:'',hostname:'nas.local'},URL,URLSearchParams,FormData,console,setInterval:()=>0,clearInterval(){},setTimeout:()=>0,clearTimeout(){}};
vm.createContext(context);vm.runInContext(fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,''),context);
const evaluate=code=>vm.runInContext(code,context);
evaluate('session={user:{role:"admin",name:"admin"}};page="vms";renderedRoute="#vms";const originalBindPage=bindPage;bindPage=()=>{};renderInlineActivity=()=>{};toast=message=>{window.lastError=message;};');
(async()=>{
 let complete;context.delayed=new Promise(resolve=>complete=resolve);evaluate('pages.vms=()=>delayed;');
 node('#main').innerHTML='<section class="dark-vm">Existing VM tiles</section>';
 const refresh=evaluate('actions.refresh()');await Promise.resolve();assert.match(node('#main').innerHTML,/Existing VM tiles/);assert.doesNotMatch(node('#main').innerHTML,/Server wird geladen/);assert.equal(node('#main').attributes['aria-busy'],'true');
 complete('<section>Updated VM tiles</section>');await refresh;assert.match(node('#main').innerHTML,/Updated VM tiles/);assert.equal(node('#main').attributes['aria-busy'],undefined);
 let isoListeners=0;node('#iso-upload').addEventListener=()=>isoListeners++;evaluate('bindPage=originalBindPage;bindPage();');assert.equal(isoListeners,1);
 evaluate('pages.vms=async()=>{throw Error("libvirt unavailable");};');await evaluate('actions.refresh()');assert.match(node('#main').innerHTML,/Updated VM tiles/);assert.equal(browser.lastError,'libvirt unavailable','A failed refresh reports the error without replacing the existing view');await evaluate('actions.refresh()');assert.equal(isoListeners,1,'Failed retained refreshes do not duplicate the ISO-upload listener');
 let navigation=0,opened;
 browser.TitanVMExtensions.selectionState=()=>({id:'vm-one',tab:'backups'});
 context.latest={vms:[{id:'vm-one',name:'Existing VM',state:'shut off'}]};evaluate('api=async()=>latest;');
 context.reopen=target=>{opened=target;};context.navigated=()=>navigation++;
 evaluate('actions["vm-extensions"]=reopen;navigate=navigated;');const previous=node('#main').innerHTML;await evaluate('refreshVMWorkspace()');
 assert.equal(navigation,0,'Selected VM refresh does not rebuild the manager');assert.equal(opened.dataset.id,'vm-one');assert.equal(opened.dataset.tab,'backups');assert.equal(node('#main').innerHTML,previous);
 let selected={id:'vm-one',tab:'backups'},finishRefresh;opened=null;browser.TitanVMExtensions.selectionState=()=>selected;
 context.delayedRefresh=new Promise(resolve=>finishRefresh=resolve);evaluate('api=()=>delayedRefresh;');
 const oldRefresh=evaluate('refreshVMWorkspace()');await Promise.resolve();selected={id:'vm-two',tab:'console'};
 finishRefresh({vms:[{id:'vm-one'},{id:'vm-two'}]});await oldRefresh;assert.equal(opened,null,'A delayed refresh must not replace a newer selected VM or tab');
 selected={id:'vm-one',tab:'backups'};context.delayedRefresh=new Promise(resolve=>finishRefresh=resolve);const closingRefresh=evaluate('refreshVMWorkspace()');await Promise.resolve();selected=null;finishRefresh({vms:[{id:'vm-one'}]});await closingRefresh;assert.equal(opened,null,'A delayed refresh must not reopen details after Back');
 console.log('VM refresh retains the current surface during delayed/failed requests and preserves the selected detail tab.');
})().catch(error=>{console.error(error);process.exitCode=1;});
