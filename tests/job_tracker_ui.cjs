'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const tracker=require('../titan/web/job_tracker.js');
const job=(status,result={})=>({id:'job-1',status,result});
async function main(){
 const progress=[],sequence=[job('queued'),job('running',{message:'Images laden'}),job('completed',{ok:true,message:'Paket bereit'})];let calls=0;
 const completed=await tracker.wait(async path=>{assert.equal(path,'/api/jobs');return [sequence[calls++]];},'job-1',{interval:1,onProgress:row=>progress.push(row.status)});
 assert.equal(calls,3);assert.deepEqual(progress,['queued','running','completed']);assert.equal(completed.result.message,'Paket bereit');
 await assert.rejects(tracker.wait(async()=>[],'',{interval:1}),/keinen Auftrag/);
 await assert.rejects(tracker.wait(async()=>[job('failed',{error:'Docker nicht erreichbar'})],'job-1',{interval:1}),error=>error.message==='Docker nicht erreichbar'&&error.job==='job-1'&&error.result.error==='Docker nicht erreichbar');
 const partial={ok:false,completed:['container-a'],failed:[{container:'container-b',error:'Redis reagiert nicht'},{container:'container-c',error:'Datenbank nicht bereit'}]};
 await assert.rejects(tracker.wait(async()=>[job('completed',partial)],'job-1',{interval:1}),error=>error.result===partial&&error.message==='Redis reagiert nicht · Datenbank nicht bereit');
 let missing=0;await assert.rejects(tracker.wait(async()=>{missing++;return [{id:'other',status:'completed'}];},'job-1',{interval:1}),/nicht mehr in der aktuellen Liste/);assert.equal(missing,5,'Missing jobs have a bounded lookup budget');
 const before=new AbortController();before.abort();let beforeCalls=0;await assert.rejects(tracker.wait(async()=>{beforeCalls++;return [];},'job-1',{signal:before.signal,interval:1}),error=>error.name==='AbortError');assert.equal(beforeCalls,0);
 const during=new AbortController();let duringCalls=0;await assert.rejects(tracker.wait(async()=>{duringCalls++;return [job('running')];},'job-1',{signal:during.signal,interval:1,onProgress:()=>during.abort()}),error=>error.name==='AbortError');assert.equal(duringCalls,1,'Closing a pane stops polling while the accepted server job can continue');
 // A request that never settles is independently cancellable. The polling
 // helper forwards a real abort signal to fetch and rejects without waiting
 // for the unreachable server to answer.
 const hangingController=new AbortController();let hangingCalls=0,hangingSignal;
 const hanging=tracker.wait(async(path,body,options)=>{hangingCalls++;assert.equal(path,'/api/jobs');assert.equal(body,undefined);hangingSignal=options.signal;return new Promise(()=>{});},'job-1',{signal:hangingController.signal,interval:1,requestTimeout:10000});
 await Promise.resolve();await Promise.resolve();assert.equal(hangingCalls,1);assert.equal(hangingSignal.aborted,false);hangingController.abort();await assert.rejects(hanging,error=>error.name==='AbortError');assert.equal(hangingSignal.aborted,true);
 const timeoutSignals=[];await assert.rejects(tracker.wait(async(_path,_body,options)=>{timeoutSignals.push(options.signal);return new Promise(()=>{});},'job-1',{interval:1,requestTimeout:2}),error=>/Verbindung zum Auftrag unterbrochen/.test(error.message)&&/Statusabfrage antwortet nicht/.test(error.cause.message));assert.equal(timeoutSignals.length,3);assert(timeoutSignals.every(signal=>signal.aborted),'Every timed-out status fetch is cancelled');
 let timeoutRecoveryCalls=0;const recoveredSignals=[];
 const timedRecovery=await tracker.wait(async(_path,_body,options)=>{recoveredSignals.push(options.signal);return ++timeoutRecoveryCalls<3?new Promise(()=>{}):[job('completed',{ok:true,message:'Nach Netzwerkpause fertig'})];},'job-1',{interval:1,requestTimeout:2});assert.equal(timedRecovery.result.message,'Nach Netzwerkpause fertig');assert.equal(timeoutRecoveryCalls,3);assert(recoveredSignals.slice(0,2).every(signal=>signal.aborted));assert.equal(recoveredSignals[2].aborted,false);
 const recovery=[Error('Temporary network'),Error('Temporary network'),job('running'),Error('Temporary network again'),Error('Temporary network again'),job('completed',{ok:true})];let recoveredCalls=0;
 await tracker.wait(async()=>{const value=recovery[recoveredCalls++];if(value instanceof Error)throw value;return [value];},'job-1',{interval:1});assert.equal(recoveredCalls,6,'Successful reads reset the consecutive transient failure budget');
 let brokenCalls=0;await assert.rejects(tracker.wait(async()=>{brokenCalls++;throw Error('Disconnected');},'job-1',{interval:1}),error=>/Verbindung zum Auftrag unterbrochen/.test(error.message)&&error.cause.message==='Disconnected'&&error.job==='job-1');assert.equal(brokenCalls,3,'Persistent transport failure stops after three attempts');
 for(const status of [401,403]){let authCalls=0;const error=Object.assign(Error('Unauthorized'),{status});await assert.rejects(tracker.wait(async()=>{authCalls++;throw error;},'job-1',{interval:1}),actual=>actual===error);assert.equal(authCalls,1,'Authentication/authorization failure must never be retried');}
 let now=0;const sandbox={module:{exports:{}},Date:{now:()=>now++},setTimeout,clearTimeout,Error,AbortController};vm.runInNewContext(fs.readFileSync(require.resolve('../titan/web/job_tracker.js'),'utf8'),sandbox);
 let unbounded=0;await assert.rejects(sandbox.module.exports.wait(async()=>{unbounded++;return [job('unknown')];},'job-1',{interval:1,maxWait:1}),/länger als erwartet/);assert.equal(unbounded,2,'An unknown/nonterminal state cannot poll forever');
 console.log('Job tracker verifies pending completion, explicit/partial failures, bounded missing state, cancellation, transient recovery, transport/auth failures, in-flight abort, hanging-fetch timeout/recovery and elapsed timeout.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
