'use strict';
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
function harness(){
 const listeners=[],nodes=new Map(),controls=[];
 const node=key=>{if(!nodes.has(key))nodes.set(key,{textContent:'',hidden:true,disabled:false,classList:{toggle(){}},innerHTML:''});return nodes.get(key);};
 const body={querySelector:selector=>selector==='[data-package-settings]'?null:node(selector),querySelectorAll:()=>controls,contains:()=>true,addEventListener:(type,handler,options)=>listeners.push({type,handler,signal:options.signal})};
 const modal={open:false,close(){this.open=false;},addEventListener(){}};
 const browser={document:{getElementById:id=>id==='dialog-body'?body:modal,hidden:false}};
 const sandbox={window:browser,AbortController,URLSearchParams,Date,setInterval,clearInterval};
 vm.runInNewContext(fs.readFileSync(require.resolve('../titan/web/package_center.js'),'utf8'),sandbox);
 const data={installed:true,app:{id:'titan-nextcloud',name:'Nextcloud',state:'running'},phase:'degraded',primary_state:'running',primary_available:true,ready:false,running_services:2,services:[{id:'app',name:'Nextcloud',state:'running',ready:true},{id:'office',name:'Office',state:'exited',ready:false}],settings:[]};
 const api=async path=>path.startsWith('/api/package-details')?data:null;
 const dialog=()=>{browser.TitanPackageCenter.dispose();modal.open=true;};
 const context={api,dialog,askYesNo:async()=>false,action:async()=>({message:'Fertig'})};
 const click=command=>{const target={dataset:{packageCommand:command},disabled:false};return listeners.filter(row=>row.type==='click'&&!row.signal.aborted).at(-1).handler({target:{closest:()=>target},preventDefault(){}});};
 return {browser,body,modal,node,context,click,data,controls};
}
async function main(){
 const h=harness();let called=0,finish;
 h.context.askYesNo=async()=>{h.browser.TitanPackageCenter.dispose();h.modal.close();return true;};
 h.context.action=async(operation,args,options)=>{called++;assert.equal(operation,'app_action');assert.equal(args.action,'remove');assert.equal(options.wait,true);options.onProgress({status:'running',result:{message:'Container werden gestoppt'}});return new Promise(resolve=>finish=resolve);};
 await h.browser.TitanPackageCenter.open('titan-nextcloud',h.context);
 const operation=h.click('remove');
 for(let i=0;i<8;i++)await Promise.resolve();
 assert.equal(called,1,'Accepted shared-dialog confirmation executes exactly once');
 assert.equal(h.modal.open,true,'Package panel remains visible until the actual job finishes');
 assert.equal(h.node('[data-package-progress]').textContent,'Container werden gestoppt');
 finish({message:'Paket entfernt; Daten behalten'});await operation;
 assert.equal(h.modal.open,false,'Successful uninstall closes after the completed job');
 const aborted=harness();aborted.context.askYesNo=async()=>{aborted.browser.TitanPackageCenter.dispose();return false;};aborted.context.action=async()=>{throw Error('Should not execute');};
 await aborted.browser.TitanPackageCenter.open('titan-nextcloud',aborted.context);await aborted.click('remove');assert.equal(aborted.modal.open,true,'No restores a live package panel');
 const failure=harness();const disabled={disabled:true},enabled={disabled:false};failure.controls.push(disabled,enabled);
 failure.context.action=async(_op,_args,options)=>{assert.equal(options.wait,true);throw Error('Docker antwortet nicht');};
 const pane=await failure.browser.TitanPackageCenter.open('titan-nextcloud',failure.context);
 await assert.rejects(pane.execute('start'),/Docker antwortet nicht/);
 assert.equal(failure.node('[data-package-error]').textContent,'Docker antwortet nicht');assert.equal(failure.node('[data-package-progress]').hidden,false);
 assert.equal(disabled.disabled,true,'Error handling retains the existing state guards');assert.equal(enabled.disabled,false);
 failure.browser.TitanPackageCenter.dispose();aborted.browser.TitanPackageCenter.dispose();h.browser.TitanPackageCenter.dispose();
 const render=require('../titan/web/package_center.js').render;const content=render({...h.data,primary_state:'exited'},{container:{state:'running'}});assert.doesNotMatch(content,/App öffnen/,'Running dependencies cannot make an exited main service openable');
 const vms=require('../titan/web/vm_extensions.js');
 const vmHtml=vms.render({id:'guest',name:'<Guest>',cpus:2,memory_mb:2048},{state:'running',disks:[],networks:[],snapshots:[],guest_agent:{}},'console',{bytes:String});
 assert.match(vmHtml,/class="vm-detail-header"/);assert.match(vmHtml,/data-vmx-command="back"/);assert.match(vmHtml,/data-vmx-tab="overview"/);assert.match(vmHtml,/data-vmx-command="shutdown"/);assert.match(vmHtml,/data-vmx-command="reboot"/);assert.match(vmHtml,/class="vm-detail-content is-console"/);assert.match(vmHtml,/embedded=1/);assert.doesNotMatch(vmHtml,/<Guest>/);
 console.log('Package Yes/No restore, awaited job completion, retained errors/state guards, primary-service status and full VM pane checks passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
