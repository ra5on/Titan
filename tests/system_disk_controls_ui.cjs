'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('titan/web/system_disk_controls.js','utf8');
const GiB=1024**3,revision='a'.repeat(64);
const expandable={supported:true,available:true,reason:'Freier Platz kann übernommen werden.',revision,disk:'/dev/sda',partition:'/dev/sda4',partition_number:4,filesystem:'xfs',mountpoint:'/var',disk_size:80*GiB,partition_size:20.5*GiB,filesystem_size:20*GiB,filesystem_used:8*GiB,filesystem_available:12*GiB,partition_growable_bytes:59.5*GiB,filesystem_growable_bytes:0,growable_bytes:59.5*GiB};
class Node {
 constructor(){this.listeners=new Map();this.nodes=new Map();this.disabled=false;this.value='';this.textContent='';this.focused=false;this.dataset={};}
 querySelector(selector){return this.nodes.get(selector)||null;}
 addEventListener(type,callback){this.listeners.set(type,callback);}
 removeEventListener(type,callback){if(this.listeners.get(type)===callback)this.listeners.delete(type);}
 contains(node){return node===this||[...this.nodes.values()].some(child=>child.contains(node));}
 focus(){this.focused=true;}
 async dispatch(type){const event={target:this,prevented:false,preventDefault(){this.prevented=true;}};await this.listeners.get(type)?.(event);return event;}
}
function fixture(api,options={}){
 let now=0,sleeps=0,timerId=0;const timers=new Map();
 const context={module:{exports:{}},Date:{now:()=>now},setTimeout:(callback,delay)=>{const id=++timerId;if(delay===1500||options.expireReads){const task=setTimeout(()=>{timers.delete(id);now+=delay;if(delay===1500)sleeps++;callback();},0);timers.set(id,task);}else timers.set(id,null);return id;},clearTimeout:id=>{clearTimeout(timers.get(id));timers.delete(id);},console};vm.createContext(context);vm.runInContext(source,context);
 const ui=context.module.exports,main=new Node(),section=new Node(),open=new Node(),refresh=new Node(),status=new Node(),requests=[],dialogs=[],toasts=[];
 main.nodes.set('[data-system-disk-panel]',section);main.nodes.set('[data-system-disk-open]',open);main.nodes.set('[data-system-disk-refresh]',refresh);main.nodes.set('[data-system-disk-status]',status);
 let scope=null;
 const ctx={admin:true,api:async(path,body)=>{requests.push({path,body});return api(path,body);},toast:(message,error)=>toasts.push({message,error}),dialogRoot:()=>scope,dialog:(title,html)=>{scope=new Node();const form=new Node(),input=new Node(),status=new Node(),submit=new Node(),cancel=new Node();scope.nodes.set('[data-system-disk-form]',form);form.nodes.set('[data-system-disk-confirmation]',input);form.nodes.set('[data-system-disk-dialog-status]',status);form.nodes.set('button[type="submit"]',submit);form.nodes.set('[data-system-disk-cancel]',cancel);dialogs.push({title,html,scope,form,input,status,submit,cancel});},...options};
 const state=ui.mount(main,ctx);
 return{ui,main,section,open,refresh,status,requests,dialogs,toasts,state,get sleeps(){return sleeps;},turn:()=>new Promise(resolve=>setImmediate(resolve))};
}
(async()=>{
 const f=fixture(async()=>expandable),ui=f.ui;
 const html=ui.panel(expandable);assert(html.includes('80 GB'));assert(html.includes('20,5 GB'));assert(html.includes('20 GB'));assert(html.includes('12 GB'));assert(html.includes('59,5 GB'));assert(html.includes('data-system-disk-open'));assert(!/data-system-disk-open disabled/.test(html));assert(html.includes('aria-label="Belegter Platz'));assert(html.includes('nicht als zusätzliche Kapazität'));assert(!/mkfs|volume-create|pool-create/.test(html));
 const escaped=ui.panel({...expandable,disk:'<script>',reason:'<img onerror="bad">'});assert(escaped.includes('&lt;script&gt;'));assert(!escaped.includes('<script>'));assert(!escaped.includes('<img onerror='));assert(ui.panel({},'Fehler <script>').includes('Fehler &lt;script&gt;'));
 assert.equal(ui.bytes(null),'—');assert.equal(ui.bytes(0),'0 B');assert.equal(ui.bytes(-1),'—');assert.equal(ui.bytes('123'),'—');assert.equal(ui.bytes(NaN),'—');
 for(const data of [{...expandable,supported:false},{...expandable,available:false},{...expandable,revision:'wrong'},{...expandable,growable_bytes:0},{...expandable,growable_bytes:-1},{...expandable,growable_bytes:'123'},{...expandable,available:'true'}])assert.equal(ui.canGrow(data),false);
 assert(/data-system-disk-open disabled/.test(ui.panel(expandable,'',{admin:false})));assert.equal(ui.canGrow(expandable),true);ui.dispose();assert.equal(f.main.listeners.size,0);

 // Only a fresh status response supplies the immutable captured revision.
 let fresh={...expandable,revision:'b'.repeat(64)},queuedReads=0;
 const lifecycle=fixture(async(path,body)=>{
  if(path==='/api/system-disk')return fresh;
  if(path==='/api/actions'){assert.equal(body.operation,'system_disk_grow');assert.deepEqual(JSON.parse(JSON.stringify(body.arguments)),{expected_revision:'b'.repeat(64),confirmation:'ERWEITERN'});return{job:7};}
  if(path==='/api/jobs'){queuedReads++;if(queuedReads===1)return[{id:7,status:'queued'}];if(queuedReads===2)return[{id:7,status:'running'}];fresh={...fresh,available:false,growable_bytes:0,filesystem_size:79*GiB,partition_size:79.5*GiB,reason:'Vollständig erweitert.'};return[{id:7,status:'completed',result:{changed:true,message:'Kapazität erweitert.'}}];}
  throw new Error('Unexpected API '+path);
 });
 await lifecycle.state.open();assert.equal(lifecycle.requests[0].path,'/api/system-disk');const dialog=lifecycle.dialogs[0];assert(dialog.cancel.focused,'No remains the safe default after Yes moves to the left');assert(!dialog.input.focused);assert(dialog.html.indexOf('>Ja</button>')<dialog.html.indexOf('>Nein</button>'));assert(!dialog.html.includes('name="disk"'));assert(!dialog.html.includes('name="revision"'));
 for(const input of ['', 'erweitern', ' ERWEITERN ']){dialog.input.value=input;await dialog.form.dispatch('submit');assert(!lifecycle.requests.some(item=>item.body));assert(dialog.status.textContent.includes('exakt'));}
 dialog.input.value='ERWEITERN';dialog.form.dataset.revision='c'.repeat(64);await dialog.form.dispatch('submit');assert.equal(lifecycle.requests.filter(item=>item.body).length,1);assert.equal(queuedReads,3);assert.equal(lifecycle.sleeps,2);assert(dialog.submit.disabled);assert(dialog.input.disabled);assert.equal(dialog.status.textContent,'Kapazität erweitert.');assert(lifecycle.section.outerHTML.includes('79 GB'));assert(lifecycle.open.disabled);await dialog.form.dispatch('submit');assert.equal(lifecycle.requests.filter(item=>item.body).length,1);lifecycle.ui.dispose();

 const unavailable=fixture(async()=>({...expandable,available:false,reason:'Kein Platz hinter der Partition.'}));await unavailable.state.open();assert.equal(unavailable.dialogs.length,0);assert(unavailable.open.disabled);assert(unavailable.status.textContent.includes('Kein Platz'));unavailable.ui.dispose();
 const readOnly=fixture(async()=>{throw new Error('No request allowed');},{admin:false});await readOnly.state.open();assert.equal(readOnly.requests.length,0);assert(readOnly.toasts[0].message.includes('Administrator'));readOnly.ui.dispose();

 // A failed job forces a new status/confirmation instead of replaying a form.
 let failedPosts=0;
 const failed=fixture(async(path)=>{if(path==='/api/system-disk')return expandable;if(path==='/api/actions'){failedPosts++;return{job:'failed-job'};}return[{id:'failed-job',status:'failed',result:{error:'Layout wurde verändert.'}}];});await failed.state.open();const fd=failed.dialogs[0];fd.input.value='ERWEITERN';await fd.form.dispatch('submit');assert(fd.status.textContent.includes('Layout wurde verändert'));assert(fd.status.textContent.includes('Schließe'));await fd.form.dispatch('submit');assert.equal(failedPosts,1);assert(!failed.open.disabled);failed.ui.dispose();

 // A bounded timeout keeps another mutation disabled until the job is final.
 let final=false,polls=0;
 const timeout=fixture(async(path)=>{if(path==='/api/system-disk')return final?{...expandable,available:false,growable_bytes:0}:expandable;if(path==='/api/actions')return{job:8};polls++;return[{id:8,status:final?'completed':'running',result:{changed:true}}];});await timeout.state.open();const td=timeout.dialogs[0];td.input.value='ERWEITERN';await td.form.dispatch('submit');assert(polls<=82);assert(timeout.sleeps<=80);assert(td.status.textContent.includes('läuft noch'));assert(timeout.open.disabled);await timeout.state.open();assert.equal(timeout.requests.filter(item=>item.body).length,1);final=true;await timeout.state.refresh();assert(timeout.open.disabled);timeout.ui.dispose();

 // A hanging API read cannot bypass the polling bound or replay the mutation.
 let hangingPosts=0;const hanging=fixture(async path=>{if(path==='/api/system-disk')return expandable;if(path==='/api/actions'){hangingPosts++;return{job:10};}return new Promise(()=>{});},{expireReads:true});await hanging.state.open();const hd=hanging.dialogs[0];hd.input.value='ERWEITERN';await hd.form.dispatch('submit');assert(hd.status.textContent.includes('antwortet nicht'));assert(hanging.open.disabled);assert.equal(hangingPosts,1);await hd.form.dispatch('submit');assert.equal(hangingPosts,1);hanging.ui.dispose();

 // Disposal during status lookup never opens a stale dialog.
 let statusReply;const stale=fixture(()=>new Promise(resolve=>statusReply=resolve));const lookup=stale.state.open();stale.ui.dispose();statusReply(expandable);await lookup;assert.equal(stale.dialogs.length,0);assert.equal(stale.main.listeners.size,0);

 // Closing the dialog stops local polling/updates; accepted jobs remain remote.
 let jobReply;const closing=fixture(async path=>path==='/api/system-disk'?expandable:path==='/api/actions'?{job:9}:new Promise(resolve=>jobReply=resolve));await closing.state.open();const cd=closing.dialogs[0];cd.input.value='ERWEITERN';const submitted=cd.form.dispatch('submit');await closing.turn();const before=cd.status.textContent;closing.ui.disposeWithin(cd.scope);jobReply([{id:9,status:'completed',result:{message:'Late success'}}]);await submitted;assert.equal(cd.status.textContent,before);assert.equal(closing.toasts.length,0);assert.equal(cd.form.listeners.size,0);assert(closing.open.disabled);closing.ui.dispose();

 console.log('System disk UI: distinct capacities, escaped unknown states, fresh revision and exact confirmation, queued/running/completed/failed lifecycle, bounded timeout, no replay and stale-response/disposal checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
