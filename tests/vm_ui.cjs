'use strict';
// Exercise VM choices and logical CPU pinning without libvirt, QEMU or a host mutation.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const nodes=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',textContent:'',hidden:false,style:{},classList:{remove(){},toggle(){}},addEventListener(){},append(){},setAttribute(){},showModal(){},close(){},querySelector:node});return nodes.get(selector);};
const document={querySelector:node,querySelectorAll:()=>[],addEventListener(){},createElement:()=>({remove(){}})};
const context=vm.createContext({document,window:{addEventListener(){},getSelection:()=>({toString:()=>''})},location:{hostname:'nas',hash:'#vms'},setTimeout:()=>0,setInterval:()=>0,clearInterval(){},fetch(){throw Error('Unexpected request');},URLSearchParams,FormData,AbortController,Uint8Array,TextEncoder,TextDecoder,console});
vm.runInContext(fs.readFileSync('titan/web/vm_live.js','utf8'),context);
vm.runInContext(fs.readFileSync('titan/web/manager_views.js','utf8'),context);
const source=fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,'');
vm.runInContext(source,context);
const evaluate=expression=>vm.runInContext(expression,context);
const data=values=>{const result=new FormData();for(const [key,value]of Object.entries(values))for(const item of Array.isArray(value)?value:[value])result.append(key,item);return result;};
const control=properties=>({...properties,events:{},addEventListener(type,callback){this.events[type]=callback;}});
const options={
 cpu_topology:{cpus:[
  {id:0,online:true,core_type:'performance',core_id:0,siblings:[0,2]},
  {id:1,online:true,core_type:'efficiency',core_id:1,siblings:[1]},
  {id:2,online:true,core_type:'performance',core_id:0,siblings:[0,2]},
  {id:3,online:false,core_type:'unknown',core_id:2,siblings:[3]},
 ],warnings:['Kerntypen vom Host gemeldet.']},
 storage:[{id:'system',label:'Systemlaufwerk',path:'/var/lib/titan/vms',available:true,free_bytes:1024**4},{id:'volume:offline',label:'Offline',path:'/srv/titan/volumes/offline/vms',available:false,free_bytes:0}],
 disk_images:[{id:'share:images:linux.qcow2',name:'linux.qcow2',path:'/srv/titan/shares/images/linux.qcow2',format:'qcow2',virtual_size:64.5*1024**3}],
 isos:[],
};
const status={cpus:4,memory_total:16*1024**3};
context.options=options;context.status=status;
(async()=>{
 const html=evaluate('vmCpuFields(options,status,{cpus:2,memory_mb:4096,cpu_ids:[0,2]})');
 assert.match(html,/CPU 0/);assert.match(html,/CPU 3/);assert.match(html,/P-Kern/);assert.match(html,/E-Kern/);
 assert.match(html,/SMT mit CPU 2/);assert.match(html,/nicht exklusiv reserviert/);
 assert.match(html,/value="3"[^>]*disabled/);assert.match(html,/value="0"[^>]*checked/);
 assert.match(html,/data-group="performance"/);assert.match(html,/data-group="efficiency"/);
 assert.match(html,/name="memory_mb"[^>]*max="15360"/);
 const unknownHtml=evaluate("vmCpuFields({cpu_topology:{cpus:[{id:0,online:true,core_type:'unknown',siblings:[0]}]}},status)");
 assert.match(unknownHtml,/Typ nicht gemeldet/);assert(!unknownHtml.includes('data-group="performance"'));
 context.args=data({cpus:2,memory_mb:4096,cpu_mode:'manual',cpu_ids:[0,2]});
 assert.deepEqual(JSON.parse(JSON.stringify(evaluate('vmCpuArguments(args,options,status)'))),{cpus:2,memory_mb:4096,cpu_ids:[0,2]});
 for(const values of [[],[3],[0],[0,0],[0,'not-a-cpu']]){
  context.args=data({cpus:2,memory_mb:4096,cpu_mode:'manual',cpu_ids:values});assert.throws(()=>evaluate('vmCpuArguments(args,options,status)'),/Host-CPUs/);
 }
 context.args=data({cpus:2,memory_mb:4096,cpu_mode:'auto',cpu_ids:[3]});
 assert.deepEqual(JSON.parse(JSON.stringify(evaluate('vmCpuArguments(args,options,status)'))).cpu_ids,[]);
 context.args=data({cpus:5,memory_mb:4096,cpu_mode:'auto'});assert.throws(()=>evaluate('vmCpuArguments(args,options,status)'),/Anzahl/);
 context.args=data({cpus:2,memory_mb:32768,cpu_mode:'auto'});assert.throws(()=>evaluate('vmCpuArguments(args,options,status)'),/Arbeitsspeicher/);
 context.args=data({cpus:2,memory_mb:15361,cpu_mode:'auto'});assert.throws(()=>evaluate('vmCpuArguments(args,options,status)'),/Arbeitsspeicher/);
 context.args=data({cpus:2,memory_mb:15360,cpu_mode:'auto'});assert.equal(evaluate('vmCpuArguments(args,options,status).memory_mb'),15360);
 const storageHtml=evaluate('vmStorageField(options)');assert.match(storageHtml,/Systemlaufwerk/);assert.match(storageHtml,/value="volume:offline"[^>]*disabled/);
 for(const [id,records] of [['volume:offline',options.storage],['volume:full',[...options.storage,{id:'volume:full',label:'Volles Laufwerk',path:'/srv/full/vms',available:true,status:'full',free_bytes:0}]],['volume:missing',options.storage]]){
  context.unavailableOptions={...options,default_storage:id,storage:records};const blocked=evaluate('vmStorageField(unavailableOptions)');assert.match(blocked,new RegExp('value="'+id+'" selected disabled'));assert(!blocked.includes('value="system" selected'));assert.match(blocked,/Wähle ausdrücklich einen anderen Speicherbereich/);
 }
 const imageValues={name:'test',cpus:2,memory_mb:4096,cpu_mode:'auto',disk_source:'image',disk_image:'share:images:linux.qcow2',disk_gb:65,iso:'',storage:'system'};
 context.args=data(imageValues);
 const created=JSON.parse(JSON.stringify(evaluate('vmCreateArguments(args,options,status)')));
 assert.equal(created.iso,null);assert.equal(created.disk_image,imageValues.disk_image);assert.equal(created.disk_gb,65);assert.equal(created.storage,'system');assert(!Object.hasOwn(created,'disk_source'));
 context.args=data({...imageValues,disk_gb:64});assert.throws(()=>evaluate('vmCreateArguments(args,options,status)'),/verkleinern/);
 context.args=data({...imageValues,storage:'volume:offline'});assert.throws(()=>evaluate('vmCreateArguments(args,options,status)'),/Speicherziel/);
 context.args=data({...imageValues,disk_image:'share:images:missing.raw'});assert.throws(()=>evaluate('vmCreateArguments(args,options,status)'),/Laufwerksimage/);
 context.args=data({...imageValues,disk_source:'blank',iso:''});assert.throws(()=>evaluate('vmCreateArguments(args,options,status)'),/Installations-ISO/);
 context.args=data({...imageValues,disk_source:'blank',iso:'linux.iso',disk_gb:32});
 assert.equal(evaluate('vmCreateArguments(args,options,status).disk_image'),null);
 // Manual selection keeps offline CPUs disabled and clamps vCPU count to its pool.
 const mode=control({value:'auto'}),area=control({hidden:true}),count=control({textContent:''}),number=control({value:'3',max:'3'});
 const boxes=options.cpu_topology.cpus.map(cpu=>control({value:String(cpu.id),checked:false,disabled:!cpu.online,dataset:{coreType:cpu.core_type}}));
 const groups=['all','performance','efficiency','none'].map(group=>control({dataset:{group}}));
 const cpuMap={'[name=cpu_mode]':mode,'[data-cpu-manual]':area,'[data-cpu-count]':count,'[name=cpus]':number};
 const cpuForm={querySelector:selector=>cpuMap[selector],querySelectorAll:selector=>selector==='[name=cpu_ids]'?boxes:groups};
 context.cpuForm=cpuForm;evaluate('bindVmCpuControls(cpuForm)');
 assert.equal(area.hidden,true);mode.value='manual';mode.events.change();assert.equal(area.hidden,false);
 groups[1].events.click();assert.deepEqual(boxes.map(box=>box.checked),[true,false,true,false]);assert.equal(number.value,2);assert.equal(number.max,2);
 groups[2].events.click();assert.deepEqual(boxes.map(box=>box.checked),[false,true,false,false]);assert.equal(number.value,1);
 groups[0].events.click();assert.deepEqual(boxes.map(box=>box.checked),[true,true,true,false]);
 mode.value='auto';mode.events.change();assert.equal(area.hidden,true);assert.equal(number.max,3);
 // Switching disk source updates required inputs and prevents shrinking an imported disk.
 const sources=[control({value:'blank',checked:true}),control({value:'image',checked:false})],image=control({value:imageValues.disk_image}),iso=control({value:''}),size=control({value:'32'}),storage=control({value:'system'}),path=control({textContent:''}),imageArea=control({hidden:true});
 const sourceMap={'[name=disk_image]':image,'[name=iso]':iso,'[name=disk_gb]':size,'[name=storage]':storage,'[data-vm-storage-path]':path,'[data-vm-image]':imageArea};
 context.sourceForm={querySelector:selector=>sourceMap[selector],querySelectorAll:()=>sources};evaluate('bindVmSourceControls(sourceForm,options)');
 assert.equal(image.disabled,true);assert.equal(iso.required,true);sources[0].checked=false;sources[1].checked=true;sources[1].events.change();
 assert.equal(image.disabled,false);assert.equal(image.required,true);assert.equal(iso.required,false);assert.equal(size.min,65);assert.equal(size.value,65);assert.equal(path.textContent,'/var/lib/titan/vms');
 // An image-only host may create VMs without an ISO and submits only explicit fields.
 evaluate("session={demo:true,user:{role:'admin',csrf:'synthetic-csrf'}};dialog=(title,html,submit)=>{globalThis.dialogHtml=html;globalThis.dialogSubmit=submit;};bindVmCpuControls=()=>{};bindVmSourceControls=()=>{};");
 context.fetch=async url=>({ok:true,json:async()=>url==='/api/vm-options'?options:status});
 await evaluate("actions['vm-create']()");assert.match(context.dialogHtml,/Laufwerksimage auf dem NAS/);assert.match(context.dialogHtml,/CPU 0/);assert.match(context.dialogHtml,/Speicherort/);
 context.args=data(imageValues);let submitted;
 context.fetch=async(url,request)=>{submitted=JSON.parse(request.body);return {ok:true,json:async()=>({job:'test-job'})};};
 await evaluate('dialogSubmit(args)');assert.equal(submitted.operation,'vm_create');assert.equal(submitted.arguments.disk_image,imageValues.disk_image);assert(!Object.hasOwn(submitted.arguments,'cpu_mode'));
 const machine={id:'test-id',name:'test',state:'shut off',cpus:2,memory_mb:4096,cpu_ids:[0,2],disk_path:'/srv/titan/vms/test.qcow2',virtual_size:65*1024**3,iso:null};
 context.fetch=async url=>({ok:true,json:async()=>url==='/api/vms'?{available:true,vms:[machine]}:{items:[]}});
 const page=await evaluate('pages.vms()');assert.match(page,/data-action="vm-create"[^>]*class=|data-action="vm-create"/);assert(!/data-action="vm-create"[^>]*disabled/.test(page));assert.match(page,/data-manager-search="[^"]*cpu 0 cpu 2/);assert.match(page,/\/srv\/titan\/vms\/test.qcow2/);assert.match(page,/vm-machine-card/);assert.match(page,/RAM auf NAS \(RSS\)/);assert.doesNotMatch(page,/vm-row-configuration/);
 context.fetch=async url=>({ok:true,json:async()=>url==='/api/vm-options'?options:status});context.target={dataset:{id:'test-id'}};
 await evaluate("actions['vm-edit'](target)");assert.match(context.dialogHtml,/value="0"[^>]*checked/);
 context.args=data({cpus:2,memory_mb:4096,cpu_mode:'auto'});context.fetch=async(url,request)=>{submitted=JSON.parse(request.body);return {ok:true,json:async()=>({job:'test-job-edit'})};};
 await evaluate('dialogSubmit(args)');assert.equal(submitted.operation,'vm_update');assert.deepEqual(submitted.arguments.cpu_ids,[]);
 console.log('VM UI: image-only creation, storage selection, image size, CPU topology, pinning validation and edit policy passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
