'use strict';
// Exercise the real VM selection controller in a retained manager, without a VM or host mutation.
const assert=require('node:assert/strict'),fs=require('node:fs'),script=require('node:vm');
class Element{
 constructor(dataset={}){this.dataset={...dataset};this.attributes={};this.nodes=new Map();this.listeners=[];this.disabled=false;this.hidden=false;this.textContent='';this.classes=new Set();this.classList={add:v=>this.classes.add(v),remove:v=>this.classes.delete(v),toggle:(v,on)=>on?this.classes.add(v):this.classes.delete(v)};}
 setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}
 focus(){this.focused=true;}
 set innerHTML(value){this.html=value;this.nodes.clear();for(const selector of ['[data-vmx-content]','[data-vmx-status]','[data-vmx-error]','[data-vmx-live]','[data-vmx-command="back"]'])this.nodes.set(selector,new Element());for(const id of ['overview','console','hardware','network','backups'])this.nodes.set(`[data-vmx-tab="${id}"]`,new Element({vmxTab:id}));}
 get innerHTML(){return this.html||'';}
 querySelector(selector){return this.nodes.get(selector)||null;}
 querySelectorAll(selector){return selector==='[data-vmx-command],[data-vmx-tab]'?[...this.nodes.values()]:[];}
 contains(){return true;}
 addEventListener(type,handler,{signal}={}){this.listeners.push({type,handler,signal});}
 async dispatch(type,target,extra={}){const event={target:{closest:()=>target},preventDefault(){this.defaultPrevented=true;},...extra};for(const row of this.listeners.filter(row=>row.type===type&&!row.signal?.aborted))await row.handler(event);return event;}
}
function harness(){
 const manager=new Element(),host=new Element(),master=new Element(),rows=['one','two'].map(id=>{const row=new Element({vmRow:id});row.nodes.set('.vm-row-select',new Element());return row;});manager.html='original master list and filters';manager.nodes.set('[data-vm-detail-host]',host);manager.nodes.set('.vm-master-pane',master);manager.querySelectorAll=selector=>selector==='[data-vm-row]'?rows:[];
 const timers=new Map();let timer=0;
 const browser={document:{hidden:false,getElementById:()=>new Element()},TitanVMLive:{render:()=>'<div class="vm-live-grid">Measured VM resources</div>'}};
 const sandbox={window:browser,AbortController,URLSearchParams,Date,FormData,setInterval:fn=>{timers.set(++timer,fn);return timer;},clearInterval:id=>timers.delete(id)};
 script.runInNewContext(fs.readFileSync('titan/web/vm_extensions.js','utf8'),sandbox);
 const vms=['one','two'].map(id=>({id,name:id,cpus:2,memory_mb:2048,firmware:'uefi',state:'shut off'}));
 const extension=id=>({state:vms.find(vm=>vm.id===id).state,disks:[],networks:[],snapshots:[],guest_agent:{message:'Agentstatus'},snapshot_note:'Snapshot der VM'});
 let back=0;
 const context={container:manager,api:async path=>path==='/api/vms'?{vms}:path==='/api/vm-options'?{storage:[]}:extension(new URLSearchParams(path.split('?')[1]).get('vm')),bytes:String,dialog(){throw Error('Details must remain inside the application');},action:async()=>({message:'Erledigt'}),askYesNo:async()=>true,onBack(){back++;}};
 const command=name=>new Element({vmxCommand:name});
 return{manager,host,master,rows,timers,browser,ui:browser.TitanVMExtensions,vms,context,command,back:()=>back};
}
(async()=>{
 const h=harness();await h.ui.open(h.vms[0],h.context);
 assert.equal(h.manager.innerHTML,'original master list and filters','Opening details retains list and filters');assert.equal(h.host.hidden,false);assert.equal(h.manager.dataset.vmSelected,'one');assert.equal(h.rows[0].classes.has('is-selected'),true);assert.equal(h.rows[0].querySelector('.vm-row-select').attributes['aria-current'],'true');assert.equal(h.timers.size,1);assert.match(h.host.innerHTML,/role="tablist"/);assert.match(h.host.innerHTML,/role="tabpanel" id="vmx-panel-overview"/);
 assert.equal(h.master.hidden,true,'The retained tile list is hidden so details use the full window');assert.equal(h.host.querySelector('[data-vmx-command="back"]').focused,true,'Opening details moves focus to the back button');
 const originalSignal=h.host.listeners.find(row=>row.type==='click').signal;
 await h.ui.open(h.vms[1],h.context);assert.equal(originalSignal.aborted,true);assert.equal(h.manager.dataset.vmSelected,'two');assert.equal(h.rows[0].classes.has('is-selected'),false);assert.equal(h.rows[1].classes.has('is-selected'),true);assert.equal(h.timers.size,1,'One live timer is retained for the selected overview');
 await h.host.dispatch('click',new Element({vmxTab:'hardware'}));assert.equal(h.manager.dataset.vmDetailTab,'hardware');assert.equal(h.timers.size,0,'Hardware table does not start duplicate metric polls');assert.match(h.host.innerHTML,/data-vmx-command="disk-add"/);assert.doesNotMatch(h.host.innerHTML,/data-vmx-live/);assert.equal(h.host.querySelector('[data-vmx-tab="hardware"]').focused,true);
 const keyboard=await h.host.dispatch('keydown',new Element({vmxTab:'hardware'}),{key:'End'});assert.equal(keyboard.defaultPrevented,true);assert.equal(h.manager.dataset.vmDetailTab,'backups');assert.equal(h.host.querySelector('[data-vmx-tab="backups"]').focused,true);
 h.vms[1].state='running';await h.host.dispatch('click',h.command('console'));assert.equal(h.manager.dataset.vmDetailTab,'console');assert.match(h.host.innerHTML,/src="\/console.html\?vm=two&embedded=1"/);assert.match(h.host.innerHTML,/class="vm-detail-content is-console"/);assert.deepEqual(JSON.parse(JSON.stringify(h.ui.selectionState())),{id:'two',tab:'console'});
 await h.host.dispatch('click',h.command('back'));assert.equal(h.host.hidden,true);assert.equal(h.host.innerHTML,'');assert.equal(h.manager.classes.has('has-vm-detail'),false);assert.equal(h.manager.dataset.vmSelected,undefined);assert.equal(h.rows[1].querySelector('.vm-row-select').focused,true);assert.equal(h.back(),0,'Returning from selection does not reload the entire page');assert.equal(h.ui.selectionState(),null);
 assert.equal(h.master.hidden,false,'Back restores the retained tiles and filters');
 await h.ui.open(h.vms[0],h.context);const activeSignal=h.host.listeners.filter(row=>row.type==='click').at(-1).signal;h.ui.closeSelection(h.manager);assert.equal(activeSignal.aborted,true);assert.equal(h.timers.size,0);assert.equal(h.host.hidden,true);
 // A slower selection cannot replace a newer machine after its requests resolve.
 const race=harness(),baseApi=race.context.api;let finish;
 race.context.api=path=>path==='/api/vm-extensions?vm=one'?new Promise(resolve=>finish=resolve):baseApi(path);
 const first=race.ui.open(race.vms[0],race.context);await race.ui.open(race.vms[1],race.context);finish({state:'shut off',guest_agent:{},disks:[],networks:[],snapshots:[]});await first;assert.equal(race.manager.dataset.vmSelected,'two');assert.match(race.host.innerHTML,/<h2>two<\/h2>/);race.ui.dispose();
 // Actions await job completion, retain selection, show real errors and restore state guards.
 const operations=harness();let calls=0;
 operations.context.action=async(name,args,options)=>{calls++;assert.equal(name,'vm_action');assert.equal(args.vm,'one');assert.equal(args.action,'start');assert.equal(options.wait,true);options.onProgress({status:'running',result:{message:'VM startet'}});operations.vms[0].state='running';return{message:'VM gestartet'};};
 await operations.ui.open(operations.vms[0],operations.context);await operations.host.dispatch('click',operations.command('start'));assert.equal(calls,1);assert.equal(operations.manager.dataset.vmSelected,'one');assert.equal(operations.host.querySelector('[data-vmx-status]').textContent,'VM gestartet');assert.match(operations.host.innerHTML,/data-vmx-command="shutdown"/);
 operations.context.action=async()=>{throw Error('libvirt antwortet nicht');};await operations.ui.open(operations.vms[0],operations.context);await operations.host.dispatch('click',operations.command('shutdown'));assert.equal(operations.host.querySelector('[data-vmx-error]').hidden,false);assert.equal(operations.host.querySelector('[data-vmx-error]').textContent,'libvirt antwortet nicht');operations.ui.dispose();h.ui.dispose();
 console.log('VM workspace: full detail pane, retained tiles and filters, selection/state guards, async races, live timer cleanup, embedded full console, keyboard tabs, back focus, awaited actions and errors passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
