/* Share short-lived read requests across same-origin desktop windows. */
(function(root){
 'use strict';
 function create(){
  const cache=new Map();let epoch=0;
  return {clear(){epoch++;cache.clear();},async read(key,loader){
   const now=Date.now(),old=cache.get(key);if(old&&(old.pending||old.until>now))return structuredClone(await old.promise);
   const generation=epoch,entry={pending:true,until:0,promise:Promise.resolve().then(loader)};cache.set(key,entry);
   try{const value=await entry.promise;entry.pending=false;entry.until=Date.now()+2000;return structuredClone(value);}catch(error){if(generation===epoch&&cache.get(key)===entry)cache.delete(key);throw error;}
  }};
 }
 if(typeof module==='object')module.exports={create};
 if(root){try{root.TitanSharedPolling=root.parent!==root&&root.parent.location.origin===root.location.origin?root.parent.TitanSharedPolling||create():create();}catch{root.TitanSharedPolling=create();}}
})(typeof window==='undefined'?null:window);
