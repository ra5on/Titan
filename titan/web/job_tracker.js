'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanJobs=ui;})(typeof window==='undefined'?null:window,function(){
 function pause(ms,signal){return new Promise((resolve,reject)=>{const stop=()=>{clearTimeout(timer);signal?.removeEventListener('abort',stop);reject(Object.assign(new Error('Die Ansicht wurde geschlossen. Der angenommene Auftrag läuft im Hintergrund weiter.'),{name:'AbortError'}));};const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},ms);if(signal?.aborted)stop();else signal?.addEventListener('abort',stop,{once:true});});}
 function request(api,signal,timeout){return new Promise((resolve,reject)=>{const controller=new AbortController();let settled=false;const finish=(fn,value)=>{if(settled)return;settled=true;clearTimeout(timer);signal?.removeEventListener('abort',stop);fn(value);};const stop=()=>{controller.abort();finish(reject,Object.assign(Error('Die Ansicht wurde geschlossen. Der Auftrag läuft im Hintergrund weiter.'),{name:'AbortError'}));};const timer=setTimeout(()=>{controller.abort();finish(reject,Error('Die Statusabfrage antwortet nicht.'));},timeout);if(signal?.aborted){stop();return;}signal?.addEventListener('abort',stop,{once:true});Promise.resolve().then(()=>api('/api/jobs',undefined,{signal:controller.signal})).then(value=>finish(resolve,value),error=>finish(reject,error));});}
 async function wait(api,id,{onProgress=()=>{},signal,interval=1000,maxWait=1200000,requestTimeout=15000}={}){
  if(typeof id!=='string'||!id)throw Error('Der Server hat keinen Auftrag bestätigt.');
  const started=Date.now();let missing=0,disconnected=0;
  while(true){if(signal?.aborted)throw Object.assign(Error('Die Ansicht wurde geschlossen. Der Auftrag läuft im Hintergrund weiter.'),{name:'AbortError'});
   let rows;try{rows=await request(api,signal,requestTimeout);disconnected=0;}catch(error){if(error.name==='AbortError'||[401,403].includes(error.status))throw error;if(++disconnected>=3||Date.now()-started>maxWait)throw Object.assign(Error('Verbindung zum Auftrag unterbrochen. Er kann im Hintergrund weiterlaufen; Zustand unter Aktivitäten prüfen.'),{job:id,cause:error});await pause(interval,signal);continue;}const job=rows.find(row=>row.id===id);
   if(job){missing=0;onProgress(job);if(job.status==='failed'||job.result?.ok===false){const detail=job.result||{},failures=(detail.failed||[]).map(row=>row.error).filter(Boolean);throw Object.assign(Error(detail.error||failures.join(' · ')||'Der Auftrag ist fehlgeschlagen.'),{result:detail,job:id});}if(job.status==='completed')return job;}
   else if(++missing>=5)throw Object.assign(Error('Der Auftrag ist nicht mehr in der aktuellen Liste. Bitte den Zustand der Anwendung prüfen.'),{job:id});
   if(Date.now()-started>maxWait)throw Object.assign(Error('Der Auftrag läuft länger als erwartet. Sein Zustand bleibt unter Aktivitäten sichtbar.'),{job:id});
   await pause(interval,signal);
  }
 }
 return {wait};
});
