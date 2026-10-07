'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanLoginUpdates=ui;})(typeof window==='undefined'?null:window,function(){
 async function check({user,embedded=false,api,wait,signal,onAvailable=()=>{}}){
  if(user?.role!=='admin'||embedded||signal?.aborted)return null;
  const submitted=await api('/api/updates/check',{update_kind:'all'},{signal});
  const job=await wait(api,submitted.job,{signal,maxWait:120000});
  if(signal?.aborted)return null;
  const offer=job.result||{};
  if(offer.available===true&&!offer.error)onAvailable(offer);
  return offer;
 }
 return {check};
});
