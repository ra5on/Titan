'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const editor=require('../titan/web/file_editor.js'),LIMIT=1048576,initialRevision='a'.repeat(64),nextRevision='b'.repeat(64);
class Node{
 constructor(){this.nodes=new Map();this.listeners=new Map();this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.textContent='';this.className='';this.style={};this.selectionStart=0;this.selectionEnd=0;this.attributes={};}
 querySelector(selector){return this.nodes.get(selector)||null;}
 contains(node){return node===this||[...this.nodes.values()].some(child=>child.contains(node));}
 addEventListener(type,callback){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(callback);}
 removeEventListener(type,callback){const callbacks=this.listeners.get(type);callbacks?.delete(callback);if(!callbacks?.size)this.listeners.delete(type);}
 setAttribute(name,value){this.attributes[name]=value;}
 focus(){this.focused=true;}
 setRangeText(text,start,end,mode){this.value=this.value.slice(0,start)+text+this.value.slice(end);this.selectionStart=mode==='end'?start+text.length:start;this.selectionEnd=start+text.length;}
 dispatch(type,details={}){const event={type,target:this,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},stopPropagation(){this.stopped=true;},...details};for(const callback of [...(this.listeners.get(type)||[])])callback(event);return event;}
}
function fixture(api,options={},ui=editor){
 const scope=new Node(),form=new Node(),nodes={};scope.nodes.set('[data-file-editor-form]',form);
 for(const name of ['content','save','status','error','size','cursor','wrap','close-guard','continue','discard']){nodes[name]=new Node();form.nodes.set('[data-file-editor-'+name+']',nodes[name]);}
 nodes['close-guard'].hidden=true;
 const requests=[],toasts=[],closes=[];
 const opts={api:async(path,body)=>{requests.push({path,body});return api(path,body);},toast:message=>toasts.push(message),close:()=>closes.push('closed'),share:'test',path:'unknown.extension',text:'initial\n',file:{revision:initialRevision},...options};
 const state=ui.mount(scope,opts);
 return{ui,scope,form,nodes,state,requests,toasts,closes,options:opts,input:value=>{nodes.content.value=value;nodes.content.dispatch('input');},turn:()=>new Promise(resolve=>setImmediate(resolve))};
}
function savedFile(write,revision=nextRevision){return{data:write.data,total:Buffer.from(write.data,'base64').length,revision};}
(async()=>{
 const html=editor.render({share:'@system',path:'etc/<script>.some-extension',text:'</textarea><script>alert(1)</script>'});
 assert(html.includes('/etc/&lt;script&gt;.some-extension'));assert(!html.includes('</textarea><script>'));assert(html.includes('&lt;/textarea&gt;'));assert(html.includes('data-file-editor-form'));assert(html.includes('Strg/Cmd+S'));assert(html.includes('Textdateien mit jeder Dateiendung'));assert(html.includes('data-file-editor-close-guard'));assert(html.includes('Weiter bearbeiten'));assert(html.includes('Änderungen verwerfen und schließen'));
 const bomDoc=editor.documentText({text:'\uFEFFfirst\r\nnext\r\n'});assert.deepEqual(bomDoc,{text:'first\nnext\n',bom:true,newline:'crlf',mixed:false});
 assert.equal(editor.documentText({text:'first\rsecond\r'}).newline,'cr');assert.equal(editor.documentText({text:'first\nsecond\r\n'}).mixed,true);assert(editor.render({text:'one\r\ntwo\n'}).includes('gemischte Zeilenenden'));
 assert.deepEqual(editor.encode('🙂'),{data:Buffer.from('🙂').toString('base64'),size:4});assert.throws(()=>editor.encode('\0'),/Nullzeichen/);assert.throws(()=>editor.encode('\ud800'),/Unicode/);assert.throws(()=>editor.encode('ä'.repeat(LIMIT/2+1)),/1 MiB/);assert.equal(editor.encode('a'.repeat(LIMIT)).size,LIMIT);

 // Each save stays open and adopts a fresh revision only after exact byte readback.
 let written,sequence=0;
 const f=fixture(async(path,body)=>{assert.equal(path,'/api/files');if(body.action==='write'){written=body;sequence++;return{ok:true};}return savedFile(written,sequence===1?nextRevision:'c'.repeat(64));});
 assert.equal(f.nodes.content.value,'initial\n');assert.equal(f.nodes.status.textContent,'Unverändert');assert(f.nodes.save.disabled);assert(f.nodes.content.focused);assert.equal(await f.state.save(),false);assert.equal(f.requests.length,0);
 f.input('first edit\n');assert.equal(f.nodes.status.textContent,'Ungespeichert');assert(!f.nodes.save.disabled);assert(f.state.isDirty());assert.equal(f.state.canClose(),false);assert(!f.nodes['close-guard'].hidden);assert(f.nodes.continue.focused);f.nodes.continue.dispatch('click');assert(f.nodes['close-guard'].hidden);assert(f.state.isDirty());assert.equal(f.nodes.content.value,'first edit\n');assert.equal(f.closes.length,0);
 assert.equal(await f.state.save(),true);assert.equal(f.requests.length,2);assert.equal(f.requests[0].body.revision,initialRevision);assert.equal(f.requests[1].body.action,'read');assert.equal(f.requests[1].body.size,LIMIT+1);assert.equal(f.nodes.status.textContent,'Gespeichert');assert(!f.state.isDirty());assert.equal(f.form.listeners.size,1);assert.equal(f.toasts.length,1);
 // Changing surrounding filemanager selection and original metadata cannot redirect an editor.
 f.options.share='different';f.options.path='elsewhere';f.options.file.revision='d'.repeat(64);f.input('second edit\n');assert(await f.state.save());assert.equal(f.requests[2].body.share,'test');assert.equal(f.requests[2].body.path,'unknown.extension');assert.equal(f.requests[2].body.revision,nextRevision);assert.equal(f.nodes.content.value,'second edit\n');assert.equal(f.toasts.length,2);assert(f.state.canClose());
 f.nodes.wrap.checked=true;f.nodes.wrap.dispatch('change');assert.equal(f.nodes.content.wrap,'soft');assert.equal(f.nodes.content.style.whiteSpace,'pre-wrap');f.nodes.wrap.checked=false;f.nodes.wrap.dispatch('change');assert.equal(f.nodes.content.wrap,'off');
 f.nodes.content.selectionStart=7;f.nodes.content.dispatch('select');assert.equal(f.nodes.cursor.textContent,'Zeile 1, Spalte 8');editor.disposeWithin(f.scope);assert.equal(f.form.listeners.size,0);assert.equal(f.nodes.content.listeners.size,0);

 // Ctrl/Cmd+S suppresses browser save and the global legacy submit handler.
 let keyWrite;
 const keys=fixture(async(path,body)=>body.action==='write'?(keyWrite=body,{ok:true}):savedFile(keyWrite));keys.input('keyboard edit');const keyEvent=keys.nodes.content.dispatch('keydown',{key:'S',ctrlKey:true});assert(keyEvent.defaultPrevented);assert(keyEvent.stopped);await keys.turn();assert.equal(keys.requests.filter(item=>item.body.action==='write').length,1);assert(!keys.state.isDirty());keys.input('command edit');const cmd=keys.nodes.content.dispatch('keydown',{key:'s',metaKey:true});assert(cmd.defaultPrevented);await keys.turn();assert.equal(keys.requests.filter(item=>item.body.action==='write').length,2);editor.disposeWithin(keys.scope);

 // BOM, CRLF and legacy CR survive repeated edits, independent of extension.
 for(const input of ['\uFEFFa\r\nb\r\n','a\rb\r']){
  let write;const source=fixture(async(path,body)=>body.action==='write'?(write=body,{ok:true}):savedFile(write),{text:input,path:'config.weird'});source.input(source.nodes.content.value+'new\n');assert(await source.state.save());const originalBOM=input.startsWith('\uFEFF')?'\uFEFF':'',ending=input.includes('\r\n')?'\r\n':'\r';assert.equal(Buffer.from(write.data,'base64').toString('utf8'),originalBOM+'a'+ending+'b'+ending+'new'+ending);source.ui.disposeWithin(source.scope);
 }

 // Editing while a save runs retains the newer buffer; a duplicate save cannot race.
 let resolveWrite,write;
 const busy=fixture(async(path,body)=>body.action==='write'?(write=body,new Promise(resolve=>resolveWrite=resolve)):savedFile(write));busy.input('captured');assert.equal(busy.state.canClose(),false);assert(!busy.nodes['close-guard'].hidden);const pending=busy.state.save();await busy.turn();assert.equal(busy.nodes.status.textContent,'Speichert …');assert.equal(busy.form.attributes['aria-busy'],'true');assert.equal(busy.state.canClose(),false);assert(busy.nodes['close-guard'].hidden);assert.equal(busy.closes.length,0);assert.equal(await busy.state.save(),false);busy.nodes['close-guard'].hidden=false;busy.nodes.discard.dispatch('click');assert.equal(busy.closes.length,0);assert(busy.nodes.discard.disabled);busy.nodes.continue.dispatch('click');assert(busy.nodes['close-guard'].hidden);busy.input('typed during request');resolveWrite({ok:true});assert(await pending);assert.equal(busy.nodes.content.value,'typed during request');assert(busy.state.isDirty());assert(!busy.nodes.save.disabled);assert.equal(busy.requests.filter(item=>item.body.action==='write').length,1);editor.disposeWithin(busy.scope);

 // Discard is a deliberate inline action, never a native browser dialog or a write.
 const discarded=fixture(async()=>{throw new Error('Discard must not write.');});discarded.input('discarded buffer');discarded.nodes.discard.dispatch('click');assert.equal(discarded.closes.length,0);assert.equal(editor.canCloseWithin(discarded.scope),false);assert(!discarded.nodes['close-guard'].hidden);discarded.nodes.discard.dispatch('click');discarded.nodes.discard.dispatch('click');assert.equal(discarded.closes.length,1);assert.equal(discarded.requests.length,0);assert(discarded.state.canClose());assert.equal(await discarded.state.save(),false);editor.disposeWithin(discarded.scope);
 const closeFailure=fixture(async()=>({}),{close:()=>{throw new Error('Cannot close yet');}});closeFailure.input('preserved');assert.equal(closeFailure.state.canClose(),false);closeFailure.nodes.discard.dispatch('click');assert.equal(closeFailure.nodes.content.value,'preserved');assert.equal(closeFailure.state.canClose(),false);assert(!closeFailure.nodes.discard.disabled);assert(closeFailure.toasts.includes('Cannot close yet'));editor.disposeWithin(closeFailure.scope);

 // A concurrent update or an uncertain response never becomes a blind overwrite.
 const conflict=fixture(async()=>{const error=new Error('Datei wurde inzwischen verändert.');error.status=409;throw error;});conflict.input('valuable local edits');assert.equal(await conflict.state.save(),false);assert.equal(conflict.nodes.content.value,'valuable local edits');assert.equal(conflict.nodes.status.textContent,'Speichern gesperrt');assert(conflict.nodes.error.textContent.includes('Dein Text bleibt erhalten'));assert(conflict.nodes.save.disabled);conflict.input('still valuable');assert.equal(await conflict.state.save(),false);assert.equal(conflict.requests.length,1);editor.disposeWithin(conflict.scope);
 for(const mismatch of ['content','size','revision','read-error']){
  let write;const changed=fixture(async(path,body)=>{if(body.action==='write'){write=body;return{ok:true};}if(mismatch==='read-error')throw new Error('Verbindung unterbrochen');const file=savedFile(write);if(mismatch==='content')file.data=Buffer.from('changed externally').toString('base64');if(mismatch==='size')file.total++;if(mismatch==='revision')file.revision='';return file;});changed.input('save once');assert.equal(await changed.state.save(),false);assert(changed.nodes.save.disabled);assert(changed.nodes.error.textContent.includes('erneut'));assert.equal(changed.nodes.content.value,'save once');assert.equal(changed.toasts.length,0);assert.equal(await changed.state.save(),false);assert.equal(changed.requests.length,2);editor.disposeWithin(changed.scope);
 }

 // Local byte limits can be corrected without a network request or stale revision.
 let limitWrite;const limits=fixture(async(path,body)=>body.action==='write'?(limitWrite=body,{ok:true}):savedFile(limitWrite));limits.input('ä'.repeat(LIMIT/2+1));assert(limits.nodes.save.disabled);assert.equal(await limits.state.save(),false);assert.equal(limits.requests.length,0);limits.input('valid again');assert(!limits.nodes.save.disabled);assert(await limits.state.save());assert.equal(limits.requests[0].body.revision,initialRevision);editor.disposeWithin(limits.scope);

 // Closing/disposal invalidates late write and read responses without UI changes/toasts.
 for(const stage of ['write','read']){
  let reply,captured;const disposed=fixture(async(path,body)=>{if(body.action==='write'){captured=body;if(stage==='write')return new Promise(resolve=>reply=resolve);return{ok:true};}return new Promise(resolve=>reply=resolve);});disposed.input('pending');const task=disposed.state.save();await disposed.turn();const stateBefore=disposed.nodes.status.textContent;editor.disposeWithin(disposed.scope);reply(stage==='write'?{ok:true}:savedFile(captured));assert.equal(await task,false);await disposed.turn();assert.equal(disposed.nodes.status.textContent,stateBefore);assert.equal(disposed.toasts.length,0);assert.equal(disposed.requests.length,stage==='write'?1:2);assert.equal(disposed.nodes.content.listeners.size,0);
 }
 const canceled=fixture(async()=>{throw new Error('A disposed editor must not start an API call.');});canceled.input('cancel before dispatch');const canceledSave=canceled.state.save();editor.disposeWithin(canceled.scope);assert.equal(await canceledSave,false);assert.equal(canceled.requests.length,0);
 let late;
 const timed=fixture(()=>new Promise(resolve=>late=resolve),{timeoutMs:5});timed.input('timeout buffer');assert.equal(await timed.state.save(),false);assert(timed.nodes.error.textContent.includes('möglicherweise'));assert(timed.nodes.save.disabled);late({ok:true});await timed.turn();assert.equal(timed.requests.length,1);assert.equal(timed.toasts.length,0);editor.disposeWithin(timed.scope);

 // Tab supports single/multiple lines and Shift+Tab; ordinary keyboard shortcuts remain free.
 const textarea=new Node();textarea.value='one\ntwo\nthree';textarea.selectionStart=0;textarea.selectionEnd=8;editor.indent(textarea);assert.equal(textarea.value,'  one\n  two\nthree');assert.equal(textarea.selectionStart,2);assert.equal(textarea.selectionEnd,12);editor.indent(textarea,true);assert.equal(textarea.value,'one\ntwo\nthree');assert.equal(textarea.selectionStart,0);assert.equal(textarea.selectionEnd,8);textarea.selectionStart=1;textarea.selectionEnd=1;editor.indent(textarea);assert.equal(textarea.value,'o  ne\ntwo\nthree');assert.equal(textarea.selectionStart,3);
 textarea.value='\n  second\n';textarea.selectionStart=0;textarea.selectionEnd=0;editor.indent(textarea,true);assert.equal(textarea.value,'\n  second\n');assert.equal(textarea.selectionStart,0);assert.equal(textarea.selectionEnd,0);textarea.selectionStart=0;textarea.selectionEnd=9;editor.indent(textarea,true);assert.equal(textarea.value,'\nsecond\n');assert.equal(textarea.selectionStart,0);assert.equal(textarea.selectionEnd,7);
 assert.throws(()=>fixture(async()=>({}),{file:{revision:''}}),/Dateiversion/);

 // Browser tab close warns only for changed/in-flight buffers; disposal removes it.
 const browser=new Node(),context={window:browser,module:{exports:{}},TextEncoder,btoa,setTimeout,clearTimeout,console};browser.confirm=()=>{throw new Error('Native confirm must never be used by the editor.');};vm.createContext(context);vm.runInContext(fs.readFileSync('titan/web/file_editor.js','utf8'),context);const browserEditor=context.module.exports;
 const unload=fixture(async()=>({}),{},browserEditor);assert(!browser.dispatch('beforeunload').defaultPrevented);unload.input('unsaved');assert(browser.dispatch('beforeunload').defaultPrevented);assert(!browserEditor.canCloseWithin(unload.scope));assert(!unload.nodes['close-guard'].hidden);unload.nodes.continue.dispatch('click');assert(unload.state.isDirty());assert(browser.dispatch('beforeunload').defaultPrevented);assert(!browserEditor.canCloseWithin(unload.scope));unload.nodes.discard.dispatch('click');assert.equal(unload.closes.length,1);assert(browserEditor.canCloseWithin(unload.scope));assert(!browser.dispatch('beforeunload').defaultPrevented);browserEditor.dispose();assert.equal(browser.listeners.size,0);assert(!browser.dispatch('beforeunload').defaultPrevented);
 editor.dispose();
 console.log('File editor: arbitrary suffixes, escaped content, UTF-8 byte limits, BOM/CRLF/CR preservation, repeat revision-safe saves, dirty/close guards, shortcut/tab handling, readback conflicts, bounded uncertain writes and disposal checks passed.');
})().catch(error=>{editor.dispose();console.error(error);process.exitCode=1;});
