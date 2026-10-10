'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',textContent:'',hidden:false,open:false,style:{},dataset:{},querySelectorAll:()=>[],contains:()=>false,classList:{remove(){},toggle(){}},addEventListener(){},append(){},setAttribute(){},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(selector);};
let hasWorkbench=true;
const document={querySelector:selector=>selector==='.engine-workbench'?(hasWorkbench?node(selector):null):node(selector),querySelectorAll:()=>[],addEventListener(){},createElement:()=>({remove(){}})};
const window={getSelection:()=>({toString:()=>''}),addEventListener(){}};
const context=vm.createContext({document,window,location:{hostname:'nas',hash:'#docker'},setTimeout:()=>0,setInterval:()=>0,clearInterval(){},fetch(){throw new Error('Unexpected network request');},URLSearchParams,FormData,AbortController,Uint8Array,TextEncoder,TextDecoder,console});
const source=fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,'');
vm.runInContext(source,context);
const evaluate=expression=>vm.runInContext(expression,context);
const requests=[],navigations=[],notices=[];context.widgetJobs=[];evaluate('desktopWidgets={updateJobs(value){widgetJobs=value;}}');
context.fetchJobs=async path=>{assert.equal(path,'/api/jobs');requests.push(path);return context.jobs;};
context.onNavigate=()=>{navigations.push(evaluate('page'));};
context.onToast=(message,error=false)=>{notices.push({message,error});};
evaluate("api=fetchJobs;navigate=async()=>onNavigate();toast=onToast;session={user:{name:'admin',role:'admin',csrf:'synthetic-csrf'}};page='docker';");
const job=(id,status,extra={})=>({id,status,action:'app_action',username:'admin',time:Date.now()/1000,result:status==='failed'?{error:'Container konnte nicht gestartet werden.'}:{},...extra});
function reset(jobs,watched=[]){context.jobs=jobs;context.ids=watched;evaluate('watched=new Set(ids);');requests.length=0;navigations.length=0;notices.length=0;}

(async()=>{
 // The new Docker route must adopt the backend's failed-app state immediately.
 reset([job('observed-app','failed')],['observed-app']);
 await evaluate('pollJobs()');
 assert.deepEqual(requests,['/api/jobs']);assert.deepEqual(navigations,['docker']);
 assert.deepEqual(notices,[{message:'Container konnte nicht gestartet werden.',error:true}]);
 assert.equal(evaluate("watched.has('observed-app')"),false);
 assert.equal(evaluate('jobsData[0].status'),'failed');assert.equal(context.widgetJobs.filter(j=>['queued','running'].includes(j.status)).length,0);
 // A later poll containing the same terminal result must not notify/refresh twice.
 await evaluate('pollJobs()');assert.equal(requests.length,2);assert.deepEqual(navigations,['docker']);assert.equal(notices.length,1);

 // Active watched jobs and unrelated terminal jobs must leave the manager alone.
 for(const status of ['running','queued']){
  reset([job('active',status)],['active']);await evaluate('pollJobs()');
  assert.equal(navigations.length,0);assert.equal(notices.length,0);assert(evaluate("watched.has('active')"));
  assert.equal(context.widgetJobs.filter(j=>['queued','running'].includes(j.status)).length,1);
 }
 reset([job('other-admin-failure','failed',{username:'another-admin'}),job('unobserved-completion','completed')]);
 await evaluate('pollJobs()');assert.equal(navigations.length,0);assert.equal(notices.length,0);assert.equal(evaluate('watched.size'),0);assert.equal(context.widgetJobs.filter(j=>['queued','running'].includes(j.status)).length,0);
 reset([job('our-running-job','running'),job('foreign-failure','failed',{username:'another-admin'}),job('foreign-completion','completed',{username:'another-admin'})],['our-running-job']);
 await evaluate('pollJobs()');assert.equal(navigations.length,0);assert.equal(notices.length,0);assert.equal(evaluate('watched.size'),1);assert(evaluate("watched.has('our-running-job')"));assert.equal(context.widgetJobs.filter(j=>['queued','running'].includes(j.status)).length,1);

 // Missing error text still produces the existing useful failure notice once.
 reset([job('without-error','failed',{result:{}})],['without-error']);await evaluate('pollJobs()');
 assert.deepEqual(navigations,['docker']);assert.deepEqual(notices,[{message:'Auftrag fehlgeschlagen.',error:true}]);assert.equal(evaluate('watched.size'),0);
 // Docker owns its status. Neither active nor completed work may introduce
 // the former second activity card above the full-height manager.
 for(const status of ['running','completed','failed']){
  context.latestJobs=[job('owned-'+status,status)];evaluate("page='docker';jobsData=latestJobs;renderInlineActivity();");
  assert.equal(node('#inline-activity').hidden,true,'Docker workbench suppresses duplicate global feedback');
 }
 hasWorkbench=false;
 context.latestJobs=[job('generic-failed','failed',{result:{error:'Docker <script>bad()</script> & Fehler'},username:'USER-NOT-IN-COMPACT-ROW'})];evaluate("page='apps';jobsData=latestJobs;renderInlineActivity();");
 const compact=node('#inline-activity');assert.equal(compact.hidden,false);assert.equal(compact.className,'inline-activity-strip');assert.match(compact.innerHTML,/inline-job-summary/);assert.match(compact.innerHTML,/Docker &lt;script&gt;bad\(\)&lt;\/script&gt; &amp; Fehler/);assert.match(compact.innerHTML,/data-action="job-result" data-id="generic-failed"/);assert.doesNotMatch(compact.innerHTML,/<h2>|USER-NOT-IN-COMPACT-ROW|<script>/);
 context.latestJobs=[job('generic-done','completed',{result:{message:'Daten behalten <ok>'}})];evaluate('jobsData=latestJobs;renderInlineActivity();');assert.match(compact.innerHTML,/Daten behalten &lt;ok&gt;/);assert.match(compact.innerHTML,/data-id="generic-done"/);
 context.latestJobs=[job('pending-1','queued'),job('pending-2','running'),job('older-done','completed')];evaluate('jobsData=latestJobs;renderInlineActivity();');assert.equal((compact.innerHTML.match(/inline-job-summary/g)||[]).length,2,'Only active rows are shown while jobs run');assert.doesNotMatch(compact.innerHTML,/job-result|older-done|<h2>/);
 // Suppressing Docker feedback must never bypass the system-update guard.
 hasWorkbench=true;node('[data-action=update-install]').disabled=false;context.latestJobs=[job('background-update','running',{action:'update_install'})];evaluate("page='docker';jobsData=latestJobs;renderInlineActivity();");assert.equal(compact.hidden,true);assert.equal(node('[data-action=update-install]').disabled,true);
 hasWorkbench=false;node('[data-action=update-install]').disabled=false;evaluate("page='updates';renderInlineActivity();");assert.equal(node('[data-action=update-install]').disabled,true);assert.equal(compact.hidden,true,'Unified update card owns progress feedback without a duplicate completion strip');
 console.log('Job status UI: watched Docker failures refresh and notify once, terminal jobs leave watched, active/unobserved/foreign jobs do not refresh, and running counts remain accurate; manager feedback is not duplicated, compact results escape errors and update guards persist.');
})().catch(error=>{console.error(error);process.exitCode=1;});
