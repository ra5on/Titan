'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanUploads=ui;})(typeof window==='undefined'?null:window,function(){
 const token=()=>{const bytes=new Uint8Array(32);globalThis.crypto.getRandomValues(bytes);return [...bytes].map(value=>value.toString(16).padStart(2,'0')).join('');};
 const canceled=()=>Object.assign(new Error('Upload abgebrochen.'),{canceled:true});
 function leaf(value){if(typeof value!=='string'||!value||value.length>255||value.includes('/')||value.includes('\\')||value.includes('\0')||['.','..'].includes(value))throw Error('Ungültiger Dateiname.');return value;}
 async function run({files,destination,iso=false,controller=new AbortController(),request,onProgress=()=>{},createToken=token}){
  const queue=Array.from(files||[]);destination={...destination};let completed=0,transferred=0;
  for(const file of queue){leaf(file.name);if(!Number.isSafeInteger(file.size)||file.size<0)throw Error('Ungültige Dateigröße.');if(iso&&(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.iso$/.test(file.name)||!file.size))throw Error('Wähle eine nicht leere ISO-Datei mit einfachem Dateinamen.');}
  const totalBytes=queue.reduce((sum,file)=>sum+file.size,0);
  const signal=controller.signal,check=()=>{if(signal.aborted)throw canceled();};
  try{for(let index=0;index<queue.length;index++){
   check();const file=queue[index],uploadId=iso?null:createToken(),path=[destination?.path,file.name].filter(Boolean).join('/');let offset=0,isoId=null,committed=false;
   const notify=(committing=false)=>onProgress({name:file.name,index:index+1,total:queue.length,percent:file.size?offset/file.size*100:committing?100:0,committing,completed,transferred:transferred+offset,totalBytes,overallPercent:totalBytes?(transferred+offset)/totalBytes*100:completed/Math.max(queue.length,1)*100});notify();
   try{
    do{
     check();const chunk=new Uint8Array(await file.slice(offset,offset+1024*1024).arrayBuffer());check();let binary='';for(let i=0;i<chunk.length;i+=8192)binary+=String.fromCharCode(...chunk.subarray(i,i+8192));
     const body=iso?{name:file.name,offset,total:file.size,data:btoa(binary),...(isoId?{upload_id:isoId}:{})}:{share:destination.share,path,action:'upload',upload_id:uploadId,total:file.size,offset,data:btoa(binary)};
     const result=await request(iso?'/api/isos':'/api/files',body,{signal});
     if(result.offset!==offset+chunk.length)throw Error('Server meldet eine unerwartete Upload-Position.');
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
 return {run,leaf};
});
