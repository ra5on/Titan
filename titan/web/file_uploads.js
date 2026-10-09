'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanUploads=ui;})(typeof window==='undefined'?null:window,function(){
 const token=()=>{const bytes=new Uint8Array(32);globalThis.crypto.getRandomValues(bytes);return [...bytes].map(value=>value.toString(16).padStart(2,'0')).join('');};
 const canceled=()=>Object.assign(new Error('Upload abgebrochen.'),{canceled:true});
 function leaf(value){if(typeof value!=='string'||!value||value.length>255||value.includes('/')||value.includes('\\')||value.includes('\0')||['.','..'].includes(value))throw Error('Ungültiger Dateiname.');return value;}
 // FileReader performs base64 conversion natively instead of constructing a
 // multi-megabyte binary string on the UI thread. Keep the fallback for runtimes
 // without FileReader and keep cancellation bound to the current read.
 async function encode(blob,signal){
  if(signal.aborted)throw canceled();
  if(typeof globalThis.FileReader==='function')return new Promise((resolve,reject)=>{
   const reader=new globalThis.FileReader();
   const cleanup=()=>{signal.removeEventListener('abort',abort);reader.onload=reader.onerror=reader.onabort=null;};
   const abort=()=>{cleanup();reader.abort();reject(canceled());};
   reader.onload=()=>{const value=reader.result;cleanup();if(signal.aborted)return reject(canceled());if(typeof value!=='string'||!value.includes(','))return reject(Error('Dateiblock konnte nicht gelesen werden.'));resolve(value.slice(value.indexOf(',')+1));};
   reader.onerror=()=>{const error=reader.error;cleanup();reject(error||Error('Dateiblock konnte nicht gelesen werden.'));};
   reader.onabort=()=>{cleanup();reject(canceled());};
   signal.addEventListener('abort',abort,{once:true});
   try{reader.readAsDataURL(blob);}catch(error){cleanup();reject(error);}
  });
  const chunk=new Uint8Array(await blob.arrayBuffer());if(signal.aborted)throw canceled();
  let binary='';for(let i=0;i<chunk.length;i+=8192)binary+=String.fromCharCode(...chunk.subarray(i,i+8192));return btoa(binary);
 }
 async function run({files,destination,iso=false,controller=new AbortController(),request,onProgress=()=>{},createToken=token,now=Date.now,binary=false}){
  const queue=Array.from(files||[]);destination={...destination};let completed=0,transferred=0;const started=now();
  for(const file of queue){leaf(file.name);if(!Number.isSafeInteger(file.size)||file.size<0)throw Error('Ungültige Dateigröße.');if(iso&&(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.iso$/.test(file.name)||!file.size))throw Error('Wähle eine nicht leere ISO-Datei mit einfachem Dateinamen.');}
  const totalBytes=queue.reduce((sum,file)=>sum+file.size,0);
  const signal=controller.signal,check=()=>{if(signal.aborted)throw canceled();};
  try{for(let index=0;index<queue.length;index++){
   check();const file=queue[index],uploadId=iso?null:createToken(),path=[destination?.path,file.name].filter(Boolean).join('/');let offset=0,isoId=null,committed=false;
   const notify=(committing=false)=>{const elapsed=(now()-started)/1000,bytesPerSecond=elapsed>0?(transferred+offset)/elapsed:0;onProgress({bytesPerSecond,remainingSeconds:bytesPerSecond>0?Math.ceil((totalBytes-transferred-offset)/bytesPerSecond):null,name:file.name,index:index+1,total:queue.length,percent:file.size?offset/file.size*100:committing?100:0,committing,completed,transferred:transferred+offset,totalBytes,overallPercent:totalBytes?(transferred+offset)/totalBytes*100:completed/Math.max(queue.length,1)*100});};notify();
   try{
    do{
     check();const end=Math.min(file.size,offset+(iso?1024*1024:4*1024*1024)),length=end-offset,blob=file.slice(offset,end),raw=binary&&!iso,data=raw?null:await encode(blob,signal);check();
     const body=iso?{name:file.name,offset,total:file.size,data,...(isoId?{upload_id:isoId}:{})}:{share:destination.share,path,upload_id:uploadId,total:file.size,offset,...(raw?{}:{action:'upload',data})};
     const result=await request(iso?'/api/isos':raw?'/api/file-upload':'/api/files',body,{signal,...(raw?{binary:blob}:{})});
     if(result.offset!==offset+length)throw Error('Server meldet eine unerwartete Upload-Position.');
     if(!iso&&(result.atomic!==true||result.upload_id!==uploadId))throw Error('Der Server unterstützt noch keine sicheren Datei-Uploads. Titan zuerst aktualisieren.');
     offset=result.offset;isoId=result.upload_id;notify();
    }while(offset<file.size);
    check();notify(true);
    if(!iso){
     // Commit is a short, non-abortable transaction. Cancel still stops the
     // remaining queue, while a fully committed file stays intact.
     const result=await request('/api/files',{share:destination.share,path,action:'upload',upload_id:uploadId,total:file.size,finish:true},{});
     if(result.atomic!==true||result.complete!==true||result.upload_id!==uploadId||result.offset!==file.size)throw Error('Server hat den Upload-Abschluss nicht bestätigt.');
    }
    committed=true;completed++;transferred+=file.size;
   }catch(error){
    let cleanupFailed=false;
    if(!committed)try{if(iso&&isoId)await request('/api/isos/cancel',{upload_id:isoId},{});else if(!iso){const result=await request('/api/files',{share:destination.share,path,action:'upload',upload_id:uploadId,total:file.size,cancel:true},{});if(result.atomic===true&&result.complete===true&&result.upload_id===uploadId&&result.offset===file.size){committed=true;completed++;}}}catch{cleanupFailed=true;}
    const failure=signal.aborted?canceled():error;if(cleanupFailed)failure.message+=' Temporäre Upload-Daten bleiben geschützt und werden später bereinigt.';throw failure;
   }
  }check();return {completed};}
  catch(error){error.completed=completed;if(completed)error.message+=' '+completed+' Datei'+(completed===1?'':'en')+' bereits vollständig übertragen.';throw error;}
 }
 return {run,leaf,encode};
});
