'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

class Node {
 constructor(){this.listeners=new Map();this.dataset={};this.isConnected=true;this.disabled=false;this.hidden=true;this.classList={remove(){}};}
 addEventListener(type,callback,options={}){if(!this.listeners.has(type))this.listeners.set(type,new Map());this.listeners.get(type).set(callback,options);}
 removeEventListener(type,callback){this.listeners.get(type)?.delete(callback);}
 async dispatch(type){const event={target:this,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;}};for(const [callback,options] of [...(this.listeners.get(type)||[])]){if(options.once)this.removeEventListener(type,callback);await callback(event);}return event;}
 focus(){document.activeElement=this;}
 querySelector(selector){if(selector==='button[type=submit]')return this.submit;return null;}
 showModal(){this.open=true;document.activeElement=titleClose;}
 close(){this.open=false;void this.dispatch('close');}
}
const modal=new Node(),body=new Node(),main=new Node(),titleClose=new Node(),other=new Node();
Object.defineProperty(body,'innerHTML',{get(){return this.html||'';},set(html){this.html=html;this.form=new Node();this.form.submit=new Node();this.cancel=new Node();this.notice=new Node();}});
const document={activeElement:null,querySelector(selector){if(selector==='#dialog')return modal;if(selector==='#dialog-body')return body;if(selector==='#dialog form')return body.form;if(selector==='#main')return main;return other;},querySelectorAll:()=>[],addEventListener(){}};
body.querySelector=(selector)=>selector==='[autofocus]'&&body.html.includes('autofocus')?body.cancel:selector==='[data-dialog-error]'?body.notice:null;
const context={document,window:{addEventListener(){}},location:{hash:'#files'},setInterval:()=>0,setTimeout:()=>0,clearInterval(){},URLSearchParams,console,FormData:class extends Map{constructor(){super();}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,''),context);
const evaluate=expression=>vm.runInContext(expression,context),turn=()=>new Promise(resolve=>setImmediate(resolve));
function footerButtons(html){return [...html.matchAll(/<button\b([^>]*)>([^<]*)<\/button>/g)].map(match=>({attributes:match[1],text:match[2]}));}
function positiveFirst(html,label){const buttons=footerButtons(html),positive=buttons.findIndex(button=>button.text===label),negative=buttons.findIndex(button=>/^(Nein|Abbrechen|Schließen|Weiter bearbeiten)$/.test(button.text));assert(positive>=0,label+' exists');assert(negative>positive,label+' precedes the negative action');assert.match(buttons[positive].attributes,/type="submit"|data-file-editor-discard/);}

(async()=>{
 positiveFirst(evaluate('formEnd()'),'Erstellen');
 positiveFirst(evaluate("formEnd('Ja, löschen')"),'Ja');
 assert.match(evaluate("formEnd('Speichern <script>')"),/Speichern &lt;script&gt;/);
 assert(!evaluate('formEnd()').includes('autofocus'),'Ordinary forms retain their field/default focus rules');

 // Merely opening a confirmation never accepts it; the safe answer has focus.
 const opener=new Node();document.activeElement=opener;
 const accepted=evaluate("askYesNo('<img onerror=bad> löschen?')");let answer='pending';accepted.then(value=>answer=value);
 await turn();assert.equal(answer,'pending');assert.equal(document.activeElement,body.cancel);
 assert(body.innerHTML.includes('&lt;img onerror=bad&gt;'));assert(!body.innerHTML.includes('<img'));
 assert.equal((body.innerHTML.match(/<\/form>/g)||[]).length,1,'The confirmation has one correctly closed form');
 positiveFirst(body.innerHTML,'Ja');assert.match(footerButtons(body.innerHTML).find(button=>button.text==='Nein').attributes,/type="button".*autofocus/);
 await body.form.dispatch('submit');assert.equal(await accepted,true);assert.equal(modal.open,false);assert.equal(document.activeElement,opener);
 assert.equal(modal.listeners.get('close').size,1,'Only the permanent focus-restoration listener remains');

 // Click Nein and native Escape/close each settle as false and restore focus.
 for(const method of ['negative','escape','close']){
  document.activeElement=opener;const pending=evaluate("askYesNo('Fortfahren?')");
  if(method==='negative')evaluate('actions.close()');
  else if(method==='escape'){const event=await modal.dispatch('cancel');if(!event.defaultPrevented)modal.close();}
  else modal.close();
  assert.equal(await pending,false,method);assert.equal(document.activeElement,opener);assert.equal(modal.listeners.get('close').size,1);
 }

 // An unsaved editor can refuse replacement without leaving a pending promise.
 evaluate("dialog('Editor','<p>Ungespeichert</p>')");const previous=body.innerHTML;
 context.window.TitanFileEditor={canCloseWithin:()=>false};
 assert.equal(await evaluate("askYesNo('Verwerfen?')"),false);assert.equal(body.innerHTML,previous);assert.equal(modal.open,true);
 assert.equal(modal.listeners.get('close').size,1);delete context.window.TitanFileEditor;modal.close();

 // The actual destructive route requires positive submit, including after cancel.
 const requests=[];context.fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return{ok:true,json:async()=>({})};};
 evaluate("currentShare='daten';toast=()=>{};navigate=()=>{};");context.target={dataset:{path:'ordner/datei.txt'}};
 let deletion=evaluate("actions['file-trash'](target)");await turn();assert.equal(requests.length,0);evaluate('actions.close()');await deletion;assert.equal(requests.length,0);
 deletion=evaluate("actions['file-trash'](target)");await turn();assert.equal(requests.length,0);await body.form.dispatch('submit');await deletion;
 assert.deepEqual(requests,[{url:'/api/files',body:{share:'daten',path:'ordner/datei.txt',action:'trash'}}]);

 // Submit failures remain reviewable in the open dialog and permit retry.
 evaluate("dialog('Test',`<form>${formEnd('Speichern')}`,async()=>{throw Error('Nicht gespeichert');})");
 await body.form.dispatch('submit');assert.equal(modal.open,true);assert.equal(body.notice.textContent,'Nicht gespeichert');assert.equal(body.notice.hidden,false);assert.equal(body.form.submit.disabled,false);modal.close();

 // Details have a primary action on the left and close on the right as well.
 evaluate("catalogData=[{id:'demo',name:'Demo',description:'Test'}]");context.target={dataset:{id:'demo',installed:'false',canInstall:'true'}};await evaluate("actions['app-info'](target)");
 let buttons=footerButtons(body.innerHTML);assert(buttons.findIndex(button=>button.text==='Installieren')<buttons.findIndex(button=>button.text==='Schließen'));modal.close();
 context.target.dataset.installed='true';await evaluate("actions['app-info'](target)");buttons=footerButtons(body.innerHTML);assert(buttons.findIndex(button=>button.text==='App verwalten')<buttons.findIndex(button=>button.text==='Schließen'));modal.close();

 // Inventory guards independent custom footers and already-correct embedded forms.
 const files=['app_networks.js','backup_center.js','files_controls.js','root_access.js','storage_view.js','system_disk_controls.js','terminal_controls.js','vm_extensions.js','file_editor.js','docker_workbench.js','desktop_widgets.js','identity_controls.js','security_center.js'];
 for(const file of files){const source=fs.readFileSync(path.join('titan/web',file),'utf8');assert(!/<button\b[^>]*>(?:Abbrechen|Nein|Schließen|Weiter bearbeiten)<\/button>\s*<button\b[^>]*(?:type="submit"|data-file-editor-discard)/.test(source),file+' places positive actions before cancellation');}
 const editor=require('../titan/web/file_editor.js'),editorHtml=editor.render({text:'Inhalt'});
 positiveFirst(editorHtml.slice(editorHtml.indexOf('data-file-editor-close-guard')),'Änderungen verwerfen und schließen');
 positiveFirst(editorHtml.slice(editorHtml.lastIndexOf('<div class="form-actions">')),'Speichern');
 const backup=require('../titan/web/backup_center.js');let restore;
 backup.openAppRestore('sicherung','nextcloud',true,{dialog:(title,html,submit)=>restore={html,submit},action:async(operation,args)=>requests.push({operation,args})});
 positiveFirst(restore.html,'Ja, App wiederherstellen');assert.match(footerButtons(restore.html).find(button=>button.text==='Nein').attributes,/autofocus/);
 await restore.submit(new Map([['include_data','on']]));assert.deepEqual(requests.at(-1),{operation:'backup_app_restore',args:{backup:'sicherung',app:'nextcloud',confirmation:'sicherung',include_data:true}});
 console.log('Confirmations: positive-left inventory, safe focus, Yes/No/Escape results, cleanup, blocked editor, real deletion gate, restore payload and retry passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
