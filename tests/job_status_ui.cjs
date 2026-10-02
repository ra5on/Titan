'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',textContent:'',hidden:false,open:false,style:{},dataset:{},classList:{remove(){},toggle(){}},addEventListener(){},append(){},setAttribute(){},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(selector);};
const document={querySelector:node,querySelectorAll:()=>[],addEventListener(){},createElement:()=>({remove(){}})};
const window={getSelection:()=>({toString:()=>''}),addEventListener(){}};
const context=vm.createContext({document,window,location:{hostname:'nas',hash:'#docker'},setTimeout:()=>0,setInterval:()=>0,clearInterval(){},fetch(){throw new Error('Unexpected network request');},URLSearchParams,FormData,AbortController,Uint8Array,TextEncoder,TextDecoder,console});
const source=fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,'');
vm.runInContext(source,context);
const evaluate=expression=>vm.runInContext(expression,context);
const requests=[],navigations=[],notices=[];
context.fetchJobs=async path=>{assert.equal(path,'/api/jobs');requests.push(path);return context.jobs;};
context.onNavigate=()=>{navigations.push(evaluate('page'));};
context.onToast=(message,error=false)=>{notices.push({message,error});};
evaluate("api=fetchJobs;navigate=async()=>onNavigate();toast=onToast;session={user:{name:'admin',role:'admin',csrf:'synthetic-csrf'}};page='docker';");
const job=(id,status,extra={})=>({id,status,action:'app_action',username:'admin',result:status==='failed'?{error:'Container konnte nicht gestartet werden.'}:{},...extra});
function reset(jobs,watched=[]){context.jobs=jobs;context.ids=watched;evaluate('watched=new Set(ids);');requests.length=0;navigations.length=0;notices.length=0;}

(async()=>{
 // The new Docker route must adopt the backend's failed-app state immediately.
 reset([job('observed-app','failed')],['observed-app']);
 await evaluate('pollJobs()');
 assert.deepEqual(requests,['/api/jobs']);assert.deepEqual(navigations,['docker']);
 assert.deepEqual(notices,[{message:'Container konnte nicht gestartet werden.',error:true}]);
 assert.equal(evaluate("watched.has('observed-app')"),false);
 assert.equal(evaluate('jobsData[0].status'),'failed');assert(node('#job-count').hidden);
 // A later poll containing the same terminal result must not notify/refresh twice.
 await evaluate('pollJobs()');assert.equal(requests.length,2);assert.deepEqual(navigations,['docker']);assert.equal(notices.length,1);

 // Active watched jobs and unrelated terminal jobs must leave the manager alone.
 for(const status of ['running','queued']){
  reset([job('active',status)],['active']);await evaluate('pollJobs()');
  assert.equal(navigations.length,0);assert.equal(notices.length,0);assert(evaluate("watched.has('active')"));
  assert.equal(node('#job-count').textContent,'1');assert.equal(node('#job-count').hidden,false);
 }
 reset([job('other-admin-failure','failed',{username:'another-admin'}),job('unobserved-completion','completed')]);
 await evaluate('pollJobs()');assert.equal(navigations.length,0);assert.equal(notices.length,0);assert.equal(evaluate('watched.size'),0);assert(node('#job-count').hidden);
 reset([job('our-running-job','running'),job('foreign-failure','failed',{username:'another-admin'}),job('foreign-completion','completed',{username:'another-admin'})],['our-running-job']);
 await evaluate('pollJobs()');assert.equal(navigations.length,0);assert.equal(notices.length,0);assert.equal(evaluate('watched.size'),1);assert(evaluate("watched.has('our-running-job')"));assert.equal(node('#job-count').textContent,'1');

 // Missing error text still produces the existing useful failure notice once.
 reset([job('without-error','failed',{result:{}})],['without-error']);await evaluate('pollJobs()');
 assert.deepEqual(navigations,['docker']);assert.deepEqual(notices,[{message:'Auftrag fehlgeschlagen.',error:true}]);assert.equal(evaluate('watched.size'),0);
 console.log('Job status UI: watched Docker failures refresh and notify once, terminal jobs leave watched, active/unobserved/foreign jobs do not refresh, and running counts remain accurate.');
})().catch(error=>{console.error(error);process.exitCode=1;});
