'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const uploads=require('../titan/web/file_uploads.js'),{fixture}=require('./desktop_test_dom.cjs');
const TOKEN='a'.repeat(64),destination={share:'private',path:'original'};
const file=(name,text='abc')=>({name,size:Buffer.byteLength(text),slice:(start,end)=>({arrayBuffer:async()=>Uint8Array.from(Buffer.from(text).subarray(start,end)).buffer})});
const ack=body=>({atomic:true,upload_id:body.upload_id,offset:body.finish?body.total:body.offset+Buffer.from(body.data||'','base64').length,complete:!!body.finish});
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve};};
(async()=>{
 for(const name of ['', '../a','a/b','a\\b','.', '..','a\0b'])assert.throws(()=>uploads.leaf(name));
 assert.equal(uploads.leaf('Grüße 🌍.txt'),'Grüße 🌍.txt');
 let calls=[],progress=[];
 assert.deepEqual(await uploads.run({files:[file('a.txt'),file('empty','')],destination,createToken:()=>TOKEN,request:async(url,body,options)=>{calls.push({url,body,options});return ack(body);},onProgress:value=>progress.push(value)}),{completed:2});
 assert.deepEqual(calls.map(call=>[call.body.path,!!call.body.finish,call.body.offset]),[['original/a.txt',false,0],['original/a.txt',true,undefined],['original/empty',false,0],['original/empty',true,undefined]]);assert.equal(calls[1].options.signal,undefined,'Commit is not interrupted between rename and acknowledgement');assert(progress.some(value=>value.committing&&value.percent===100));
 assert(progress.every(value=>Number.isFinite(value.overallPercent)));assert(progress.every((value,index)=>!index||value.overallPercent>=progress[index-1].overallPercent),'Overall progress never resets for the next file');
 // Aborting while the browser reads a file must prevent even its first chunk.
 let read=deferred(),controller=new AbortController();calls=[];
 let promise=uploads.run({files:[{...file('slow'),slice:()=>({arrayBuffer:()=>read.promise})},file('later')],destination,controller,createToken:()=>TOKEN,request:async(url,body,options)=>{calls.push({url,body,options});return ack(body);}});
 controller.abort();read.resolve(new Uint8Array([1,2,3]).buffer);await assert.rejects(promise,error=>error.canceled&&error.completed===0);assert.equal(calls.length,1);assert.equal(calls[0].body.cancel,true);assert.equal(calls[0].options.signal,undefined,'Cleanup uses a fresh request after the upload signal has been aborted');
 // A transport can answer after abort. The queue must still cancel that token
 // and must not append another chunk, commit, or begin the next file.
 const chunk=deferred(),started=deferred();controller=new AbortController();calls=[];const mutableDestination={...destination};
 promise=uploads.run({files:[file('a'),file('b')],destination:mutableDestination,controller,createToken:()=>TOKEN,request:async(url,body,options)=>{calls.push({url,body,options});if(!body.cancel){started.resolve();return chunk.promise;}return ack(body);}});
 await started.promise;mutableDestination.share='wrong';mutableDestination.path='wrong';controller.abort();chunk.resolve(ack(calls[0].body));await assert.rejects(promise,error=>error.canceled&&error.completed===0);assert.equal(calls.length,2);assert(calls[1].body.cancel);assert.equal(calls[1].body.share,'private');assert.equal(calls[1].body.path,'original/a','Cancellation remains bound to the upload destination even after navigating');
 // A confirmed commit is kept intact when cancellation stops the rest.
 const commit=deferred(),commitStarted=deferred();controller=new AbortController();calls=[];
 promise=uploads.run({files:[file('done'),file('never')],destination,controller,createToken:()=>TOKEN,request:async(url,body,options)=>{calls.push({url,body,options});if(body.finish){commitStarted.resolve();return commit.promise;}return ack(body);}});
 await commitStarted.promise;controller.abort();commit.resolve(ack(calls[1].body));await assert.rejects(promise,error=>error.canceled&&error.completed===1&&/bereits vollständig/.test(error.message));assert.equal(calls.length,2);assert(!calls.some(call=>call.body.cancel),'Cancel never deletes a confirmed file');
 // An old server cannot silently fall back to writing a visible partial file.
 calls=[];await assert.rejects(uploads.run({files:[file('legacy')],destination,createToken:()=>TOKEN,request:async(url,body)=>{calls.push(body);return body.cancel?ack(body):{offset:3};}}),/keine sicheren Datei-Uploads/);assert.equal(calls.length,2);assert(calls[1].cancel);assert(calls.every(body=>body.upload_id===TOKEN));
 // Failed commit cleans the private stage. A failed cleanup reports the limit.
 calls=[];await assert.rejects(uploads.run({files:[file('failed')],destination,createToken:()=>TOKEN,request:async(url,body)=>{calls.push(body);if(body.finish)throw Error('Speicher voll');if(body.cancel)throw Error('Netz weg');return ack(body);}}),/Speicher voll.*Temporäre Upload-Daten/);assert.equal(calls.at(-1).cancel,true);
 // If the commit succeeded but its HTTP reply was lost, cancel can confirm
 // completion. Count it and refresh it instead of claiming an empty failure.
 for(const abort of [false,true]){
  calls=[];controller=new AbortController();await assert.rejects(uploads.run({files:[file('committed'),file('never')],destination,controller,createToken:()=>TOKEN,request:async(url,body)=>{calls.push(body);if(body.finish){if(abort)controller.abort();throw Error('Antwort verloren');}if(body.cancel)return {atomic:true,upload_id:TOKEN,offset:3,complete:true,canceled:false};return ack(body);}}),error=>error.completed===1&&/1 Datei bereits vollständig/.test(error.message)&&Boolean(error.canceled)===abort);assert.equal(calls.length,3);assert(calls.at(-1).cancel);
 }
 // ISO uploads keep their separate API and their cancel token.
 calls=[];controller=new AbortController();await assert.rejects(uploads.run({files:[file('install.iso','x'.repeat(1024*1024+1))],iso:true,controller,request:async(url,body,options)=>{calls.push({url,body,options});if(url==='/api/isos'){controller.abort();return {upload_id:'iso-token',offset:1024*1024};}return {};}}),error=>error.canceled);assert.equal(calls.at(-1).url,'/api/isos/cancel');assert.equal(calls.at(-1).body.upload_id,'iso-token');assert.equal(calls.at(-1).options.signal,undefined);
 // Exercise the real app status functions. Progress updates must not replace
 // the cancel button between pointerdown and click, which lost user clicks.
 const source=fs.readFileSync(require.resolve('../titan/web/app.js'),'utf8'),start=source.indexOf('function uploadLabel('),end=source.indexOf('function permissionsFields',start);assert(start>=0&&end>start);
 const f=fixture();f.doc.body.innerHTML='<div id="upload-status"></div>';const box=f.doc.querySelector('#upload-status'),sandbox={document:f.doc,$:selector=>f.doc.querySelector(selector),activeUpload:{name:'a.txt',index:1,total:2,percent:10,controller:new AbortController()},esc:String};vm.createContext(sandbox);vm.runInContext(source.slice(start,end),sandbox);vm.runInContext('renderUploadStatus()',sandbox);const button=box.querySelector('[data-action="upload-cancel"]'),meter=box.querySelector('[data-upload-progress]');button.focus();sandbox.activeUpload.percent=80;vm.runInContext('renderUploadStatus()',sandbox);assert.equal(box.querySelector('[data-action="upload-cancel"]'),button);assert.equal(box.querySelector('[data-upload-progress]'),meter);assert.equal(meter.value,80);assert.equal(f.doc.activeElement,button);sandbox.activeUpload.controller.abort();vm.runInContext('renderUploadStatus()',sandbox);assert(button.disabled);assert.match(button.textContent,/abgebrochen/);
 console.log('Upload queue: atomic confirmation, empty files, canceled reads and late chunks, captured destination, commit preservation, compatibility refusal, cleanup failure, ISO cancellation and stable cancel button passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
