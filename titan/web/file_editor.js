'use strict';
// UTF-8 editing is based on file contents and a captured revision, never on a suffix.
(function(root,factory){const editor=factory(root);if(typeof module==='object'&&module.exports)module.exports=editor;if(root)root.TitanFileEditor=editor;})(typeof window==='undefined'?null:window,function(browser){
 const LIMIT=1048576,instances=new Map();
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const validRevision=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
 function documentText(options={}){
  const raw=String(options.text??''),hasBOM=raw.startsWith('\uFEFF'),body=hasBOM?raw.slice(1):raw,breaks=new Set(body.match(/\r\n|\r|\n/g)||[]),mixed=breaks.size>1;
  const newline=options.newline==='crlf'||options.newline==='\r\n'?'crlf':options.newline==='cr'||options.newline==='\r'?'cr':options.newline==='lf'||options.newline==='\n'?'lf':breaks.size===1&&breaks.has('\r\n')?'crlf':breaks.size===1&&breaks.has('\r')?'cr':'lf';
  return {text:body.replace(/\r\n|\r/g,'\n'),bom:typeof options.bom==='boolean'?options.bom:hasBOM,newline,mixed};
 }
 function render(options={}){
  const doc=documentText(options),path=options.share==='@system'?'/'+String(options.path||''):[options.share,options.path].filter(Boolean).join('/');
  return `<form class="file-editor-workspace" data-file-editor-form><div class="file-editor-heading"><p class="subtitle">${esc(path)}</p><span class="pill gray" data-file-editor-status role="status" aria-live="polite">Unverändert</span></div><div class="file-editor-toolbar"><label class="check-label"><input type="checkbox" data-file-editor-wrap> Zeilen umbrechen</label><span class="hint">UTF-8${doc.bom?' mit BOM':''} · ${doc.newline.toUpperCase()} · Strg/Cmd+S speichern</span></div><div class="field"><label for="titan-file-editor-content">Dateiinhalt</label><textarea id="titan-file-editor-content" name="content" class="file-editor" data-file-editor-content rows="18" spellcheck="false" autocapitalize="off" autocomplete="off" wrap="off">${esc(doc.text)}</textarea></div><div class="file-editor-meta hint"><span data-file-editor-size></span><span data-file-editor-cursor></span></div><p class="hint">Textdateien mit jeder Dateiendung · maximal 1 MiB. Tab rückt mit zwei Leerzeichen ein; Umschalt+Tab rückt zurück. Binäre Formate benötigen ihre eigene Anwendung.</p>${doc.mixed?'<p class="notice warning">Diese Datei enthält gemischte Zeilenenden. Beim Speichern einer Änderung werden sie auf LF vereinheitlicht.</p>':''}<p class="form-error" data-file-editor-error role="alert" hidden></p><section class="notice warning file-editor-close-guard" data-file-editor-close-guard role="alert" aria-label="Ungespeicherte Änderungen" hidden><strong>Ungespeicherte Änderungen</strong><p>Deine Änderungen wurden noch nicht gespeichert. Möchtest du weiter bearbeiten oder sie verwerfen?</p><div class="form-actions"><button type="button" class="button danger" data-file-editor-discard>Änderungen verwerfen und schließen</button><button type="button" class="button" data-file-editor-continue>Weiter bearbeiten</button></div></section><div class="form-actions"><button type="submit" class="button primary" data-file-editor-save disabled>Speichern</button><button type="button" class="button" data-action="close">Schließen</button></div></form>`;
 }
 function encode(text){
  if(text.includes('\0'))throw new Error('Binärdaten mit Nullzeichen können nicht im Texteditor gespeichert werden.');
  if(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(^|[^\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(text))throw new Error('Der Text enthält ein unvollständiges Unicode-Zeichen.');
  const bytes=new TextEncoder().encode(text);if(bytes.length>LIMIT)throw new Error('Der Text ist größer als 1 MiB.');
  let binary='';for(let index=0;index<bytes.length;index+=8192)binary+=String.fromCharCode(...bytes.subarray(index,index+8192));
  return {data:btoa(binary),size:bytes.length};
 }
 function indent(textarea,unindent=false){
  const value=textarea.value,start=textarea.selectionStart??0,end=textarea.selectionEnd??start;
  if(!unindent&&start===end){textarea.setRangeText('  ',start,end,'end');return;}
  const first=start===0?0:value.lastIndexOf('\n',start-1)+1,last=end>start&&value[end-1]==='\n'?end-1:end;
  const block=value.slice(first,last),lines=block.split('\n');
  if(!unindent){const next=lines.map(line=>'  '+line).join('\n');textarea.setRangeText(next,first,last,'select');textarea.selectionStart=start+2;textarea.selectionEnd=end+lines.length*2;return;}
  const removed=lines.map(line=>line.startsWith('\t')?1:line.startsWith('  ')?2:line.startsWith(' ')?1:0),next=lines.map((line,index)=>line.slice(removed[index])).join('\n');
  textarea.setRangeText(next,first,last,'select');textarea.selectionStart=Math.max(first,start-removed[0]);textarea.selectionEnd=Math.max(textarea.selectionStart,end-removed.reduce((sum,size)=>sum+size,0));
 }
 function disposeWithin(scope){for(const[node,state]of [...instances])if(node.isConnected===false||node===scope||scope?.contains?.(node))state.dispose();}
 function canCloseWithin(scope){for(const[node,state]of instances)if(node===scope||scope?.contains?.(node)){if(!state.canClose())return false;}return true;}
 function dispose(){for(const state of [...instances.values()])state.dispose();}
 function mount(scope,options={}){
  const form=scope?.querySelector('[data-file-editor-form]');if(!form||typeof options.api!=='function')return null;
  instances.get(form)?.dispose();
  const textarea=form.querySelector('[data-file-editor-content]'),submit=form.querySelector('[data-file-editor-save]'),status=form.querySelector('[data-file-editor-status]'),errorNode=form.querySelector('[data-file-editor-error]'),sizeNode=form.querySelector('[data-file-editor-size]'),cursorNode=form.querySelector('[data-file-editor-cursor]'),wrap=form.querySelector('[data-file-editor-wrap]'),closeGuard=form.querySelector('[data-file-editor-close-guard]'),continueButton=form.querySelector('[data-file-editor-continue]'),discardButton=form.querySelector('[data-file-editor-discard]');
  if(!textarea||!submit||!status||!errorNode)return null;
  const share=options.share,path=options.path,doc=documentText(options),listeners=[],pending=new Set();
  if(typeof share!=='string'||!share||typeof path!=='string'||!path||!validRevision(options.file?.revision))throw new Error('Dateiversion fehlt. Bitte die Datei erneut öffnen.');
  let revision=options.file.revision,baseline=doc.text,alive=true,busy=false,blocked=false,lastSaved=false,discarded=false,localError='';
  textarea.value=doc.text;textarea.wrap='off';
  const listen=(node,type,callback)=>{if(!node?.addEventListener)return;node.addEventListener(type,callback);listeners.push([node,type,callback]);};
  const dirty=()=>textarea.value!==baseline;
  const content=()=>doc.bom?'\uFEFF'+body():body();
  const body=()=>doc.newline==='crlf'?textarea.value.replace(/\r?\n/g,'\r\n'):doc.newline==='cr'?textarea.value.replace(/\n/g,'\r'):textarea.value;
  function request(body){
   const timeout=Number.isFinite(options.timeoutMs)&&options.timeoutMs>0?Math.min(options.timeoutMs,120000):45000;
   return new Promise((resolve,reject)=>{
    let done=false;const finish=(callback,value)=>{if(done)return;done=true;clearTimeout(timer);pending.delete(cancel);callback(value);};
    const cancel=()=>finish(reject,new Error('Editor geschlossen.'));
    const timer=setTimeout(()=>finish(reject,new Error('Der Server antwortet nicht rechtzeitig. Das Speichern wurde möglicherweise bereits ausgeführt.')),timeout);pending.add(cancel);
    Promise.resolve().then(()=>done||!alive?undefined:options.api('/api/files',body)).then(value=>finish(resolve,value),error=>finish(reject,error));
   });
  }
  function update(){
   if(!alive)return;
   const unsaved=dirty();status.textContent=blocked?'Speichern gesperrt':busy?'Speichert …':unsaved?'Ungespeichert':lastSaved?'Gespeichert':'Unverändert';status.className='pill '+(blocked?'red':unsaved?'purple':'gray');
   let size=0;try{size=encode(content()).size;if(!blocked&&!busy)localError='';}catch(error){if(!blocked&&!busy)localError=error.message;size=new TextEncoder().encode(content()).length;}
   if(sizeNode)sizeNode.textContent=`${size.toLocaleString('de-DE')} / ${LIMIT.toLocaleString('de-DE')} Bytes`;
   if(cursorNode){const before=textarea.value.slice(0,textarea.selectionStart??0),line=before.split('\n').length,column=before.length-before.lastIndexOf('\n');cursorNode.textContent=`Zeile ${line}, Spalte ${column}`;}
   errorNode.textContent=localError;errorNode.hidden=!localError;submit.disabled=busy||blocked||discarded||!unsaved||size>LIMIT||Boolean(localError);
   if(discardButton)discardButton.disabled=busy||discarded;if(!unsaved&&closeGuard)closeGuard.hidden=true;
   form.setAttribute?.('aria-busy',busy?'true':'false');
  }
  function fail(message){localError=message;errorNode.textContent=message;errorNode.hidden=false;}
  async function save(){
   if(!alive||busy||blocked||discarded)return false;
   if(!dirty()){update();return false;}
   let payload;try{payload=encode(content());}catch(error){fail(error.message);submit.disabled=true;return false;}
   const savedText=textarea.value,savedRevision=revision;busy=true;localError='';if(closeGuard)closeGuard.hidden=true;update();
   try{
    await request({share,path,action:'write',data:payload.data,revision:savedRevision});
    if(!alive)return false;
    const file=await request({share,path,action:'read',size:LIMIT+1});
    if(!alive)return false;
    if(!file||file.data!==payload.data||file.total!==payload.size||!validRevision(file.revision))throw new Error('Der gespeicherte Inhalt konnte nicht bestätigt werden. Die Datei könnte inzwischen verändert worden sein.');
    revision=file.revision;baseline=savedText;lastSaved=true;options.toast?.('Datei gespeichert.');return true;
   }catch(error){
    if(!alive)return false;blocked=true;fail((error.message||'Speichern fehlgeschlagen.')+' Dein Text bleibt erhalten. Öffne die Datei erneut, bevor du weiter speicherst.');return false;
   }finally{if(alive){busy=false;update();}}
  }
  const state={save,isDirty:dirty,canClose(){
   if(!alive||discarded)return true;
   if(busy){options.toast?.('Die Datei wird noch gespeichert. Bitte warte auf das Ergebnis.');return false;}
   if(!dirty())return true;
   if(typeof options.confirm==='function')return Boolean(options.confirm('Ungespeicherte Änderungen verwerfen?'));
   if(closeGuard){closeGuard.hidden=false;continueButton?.focus();}return false;
  },dispose(){if(!alive)return;alive=false;for(const cancel of [...pending])cancel();for(const[node,type,callback]of listeners)node.removeEventListener(type,callback);listeners.length=0;instances.delete(form);}};
  listen(form,'submit',event=>{event.preventDefault();event.stopPropagation?.();save();});
  listen(textarea,'input',update);listen(textarea,'click',update);listen(textarea,'keyup',update);listen(textarea,'select',update);
  listen(textarea,'keydown',event=>{
   if((event.ctrlKey||event.metaKey)&&String(event.key).toLowerCase()==='s'){event.preventDefault();event.stopPropagation?.();save();return;}
   if(event.key==='Tab'&&!event.ctrlKey&&!event.metaKey&&!event.altKey){event.preventDefault();indent(textarea,Boolean(event.shiftKey));update();}
  });
  listen(wrap,'change',()=>{textarea.wrap=wrap.checked?'soft':'off';textarea.style.whiteSpace=wrap.checked?'pre-wrap':'pre';});
  listen(continueButton,'click',()=>{if(!alive||discarded)return;if(closeGuard)closeGuard.hidden=true;textarea.focus();});
  listen(discardButton,'click',()=>{
   if(!alive||discarded||closeGuard?.hidden!==false)return;
   if(busy){options.toast?.('Die Datei wird noch gespeichert. Bitte warte auf das Ergebnis.');return;}
   if(typeof options.close!=='function'){options.toast?.('Der Editor kann gerade nicht geschlossen werden.');return;}
   discarded=true;update();try{options.close();}catch(error){discarded=false;update();options.toast?.(error.message||'Der Editor konnte nicht geschlossen werden.');}
  });
  listen(browser,'beforeunload',event=>{if(alive&&((dirty()&&!discarded)||busy)){event.preventDefault();event.returnValue='';}});
  instances.set(form,state);update();textarea.focus();return state;
 }
 return {render,mount,dispose,disposeWithin,canCloseWithin,documentText,encode,indent};
});
