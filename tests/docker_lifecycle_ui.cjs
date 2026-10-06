'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function harness(){
 const listeners=new Map(),inputs=new Map();
 const doc={hidden:false,activeElement:null,addEventListener:(type,handler)=>listeners.set(type,handler),removeEventListener:(type,handler)=>{if(listeners.get(type)===handler)listeners.delete(type);}};
 const container={ownerDocument:doc,innerHTML:'',contains:node=>node?.isTab===true,querySelectorAll:()=>[],querySelector:()=>null,addEventListener:(type,handler)=>inputs.set(type,handler),removeEventListener:(type,handler)=>{if(inputs.get(type)===handler)inputs.delete(type);}};
 const browser={TitanArtwork:{render:()=>''},TitanDevices:{fields:()=>''}};
 const sandbox={window:browser,location:{hostname:'nas.local'},setInterval,clearInterval,Map,Set,Number,String,Object,Promise};
 vm.runInNewContext(fs.readFileSync(require.resolve('../titan/web/docker_workbench.js'),'utf8'),sandbox);
 vm.runInNewContext(fs.readFileSync(require.resolve('../titan/web/location_controls.js'),'utf8'),sandbox);
 const data={available:true,containers:[{id:'a'.repeat(64),name:'Cloud',service:'app',project:'cloud',managed_app:'titan-nextcloud',state:'running',image:'nextcloud:35',networks:[],ports:{}},{id:'b'.repeat(64),name:'Redis',service:'cache',project:'cloud',managed_app:'titan-nextcloud',state:'running',image:'redis:7.4',networks:[],ports:{}}],images:[],volumes:[],networks:[]};
 const context={api:async path=>path==='/api/docker-engine'?data:{containers:{}},action:async()=>({ok:true}),dialog(){},askYesNo:async()=>true,toast(){},bytes:String};
 const click=async(op,id)=>{const control={dataset:{engineAction:op,engineId:id},disabled:false};await listeners.get('click')({target:{closest:selector=>selector.includes('data-engine-action')?control:null}});};
 const tab=async id=>{const control={dataset:{engineTab:id},isTab:true};await listeners.get('click')({target:{closest:selector=>selector==='[data-engine-tab]'?control:null}});};
 const select=id=>inputs.get('change')({target:{checked:true,dataset:{engineSelect:id},matches:selector=>selector==='[data-engine-select]'}});
 return {ui:browser.TitanDocker,container,context,data,click,tab,select,listeners};
}
async function main(){
 const h=harness();let finish,captured;
 h.context.action=async(operation,args,options)=>{captured={operation,args,options};options.onProgress({status:'running',result:{message:'Container wird gestoppt'}});return new Promise(resolve=>finish=resolve);};
 await h.ui.mount(h.container,h.context);assert.match(h.container.innerHTML,/Container Manager/);assert.match(h.container.innerHTML,/data-engine-tab="overview"[^>]*aria|aria-selected="true" data-engine-tab="overview"/);await h.tab('stacks');assert.match(h.container.innerHTML,/data-engine-group="cloud" open/);assert.match(h.container.innerHTML,/data-engine-action="package-stop"/);
 const action=h.click('remove','a'.repeat(64));for(let i=0;i<8;i++)await Promise.resolve();
 assert.equal(captured.operation,'docker_container_action');assert.equal(captured.args.container,'a'.repeat(64));assert.equal(captured.args.action,'remove');assert.equal(captured.args.stop_before_remove,true);assert.equal(captured.options.wait,true);
 assert.match(h.container.innerHTML,/Container wird gestoppt/);assert.match(h.container.innerHTML,/data-engine-action="stop"[^>]*disabled/);
 h.data.containers=h.data.containers.slice(1);finish({ok:true,scope:'container',data_retained:true,message:'Container entfernt; Daten bleiben erhalten'});await action;
 assert.match(h.container.innerHTML,/Container entfernt; Daten bleiben erhalten/);assert.match(h.container.innerHTML,/Redis/);assert.doesNotMatch(h.container.innerHTML,/>Cloud</);
 // Starting the next command clears the previous result immediately, before
 // any new progress event or completed HTTP job arrives.
 const nextOperation=h.click('stop','b'.repeat(64));for(let i=0;i<8;i++)await Promise.resolve();
 const feedback=h.container.innerHTML.match(/data-engine-status>([^<]*)<\/p>/)?.[1];assert.equal(feedback,'Aktion läuft …');assert.doesNotMatch(feedback,/Container entfernt/);finish({ok:true,message:'Redis gestoppt'});await nextOperation;assert.match(h.container.innerHTML,/Redis gestoppt/);
 h.ui.dispose();assert.equal(h.listeners.size,0,'Navigation cleans up delegated controls');
 const batch=harness();batch.context.action=async(operation,args,options)=>{assert.equal(operation,'docker_container_batch');assert.equal(args.containers.length,2);assert.equal(options.wait,true);throw Object.assign(Error('Redis reagiert nicht'),{result:{ok:false,completed:['a'.repeat(64)],failed:[{container:'b'.repeat(64),error:'Redis reagiert nicht'}]}});};
 await batch.ui.mount(batch.container,batch.context);batch.select('a'.repeat(64));batch.select('b'.repeat(64));await batch.click('batch-stop','');
 assert.match(batch.container.innerHTML,/1 erfolgreich; Redis: Redis reagiert nicht/);assert.match(batch.container.innerHTML,/engine-object-status is-error/);assert.match(batch.container.innerHTML,/engine-object-status is-complete/);batch.ui.dispose();
 const pkg=harness();pkg.context.action=async(operation,args,options)=>{assert.equal(operation,'app_action');assert.equal(args.app,'titan-nextcloud');assert.equal(args.action,'stop');assert.equal(options.wait,true);return {ok:true,scope:'package',message:'Gesamtes Paket gestoppt'};};await pkg.ui.mount(pkg.container,pkg.context);await pkg.click('package-stop','titan-nextcloud');assert.match(pkg.container.innerHTML,/Gesamtes Paket gestoppt/);pkg.ui.dispose();
 // Exercise the real creation handler rather than a parallel HTML builder.
 // An unavailable configured default stays explicitly selected until the user
 // chooses another named destination or an existing Docker volume.
 for(const state of ['offline','full','missing']){
  const create=harness(),internal={id:'system',kind:'internal',label:'Interner Speicher',path:'/var/srv/titan',available:true,capabilities:['apps']},configured={id:'volume:chosen',kind:'volume',label:'Gewähltes Laufwerk',path:'/srv/chosen',available:state!=='offline',status:state,capabilities:['apps']},catalog={default_storage:configured.id,storage:state==='missing'?[internal]:[internal,configured]},api=create.context.api;let html,submit,submitted;
  create.data.volumes=[{Name:'existing-data'}];create.context.api=async path=>path==='/api/storage-locations'?catalog:api(path);create.context.dialog=(title,body,callback)=>{html=body;submit=callback;};create.context.action=async(operation,args)=>{submitted={operation,args};return {ok:true};};await create.ui.mount(create.container,create.context);await create.click('create','');
  const storage=html.match(/<select name="data_storage" required>([^]*?)<\/select>/)[1];assert.match(storage,/value="volume:chosen" selected disabled/);assert(!storage.includes('value="system" selected'));assert(storage.includes('value="@docker-volume:existing-data"'));
  const form=new FormData();for(const [key,value]of Object.entries({name:'manual',image:'nginx:stable',data_storage:'system',target:'/data',ports:'',environment:'',memory_mb:'1024',cpus:'2',network:'bridge',restart:'unless-stopped'}))form.set(key,value);await submit(form);assert.equal(submitted.operation,'docker_container_create');assert.equal(submitted.args.config.storage_id,'system');assert(!Object.hasOwn(submitted.args.config,'volume'));assert(!Object.hasOwn(submitted.args.config,'data_storage'));
  form.set('data_storage','@docker-volume:existing-data');await submit(form);assert.equal(submitted.args.config.volume,'existing-data');assert(!Object.hasOwn(submitted.args.config,'storage_id'));create.ui.dispose();
 }
 console.log('Docker actual lifecycle controls await jobs, group stacks, retain object results, distinguish package/service scope and show partial failures.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
