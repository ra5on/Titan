'use strict';
(function(root,factory){const value=factory();if(typeof module==='object'&&module.exports)module.exports=value;if(root)root.TitanWebAccess=value;})(typeof window==='undefined'?null:window,function(){
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let current=null;
 function render(data){
  const settings=data.settings||{},pending=data.pending,disabled=pending||data.demo;
  return `<section class="panel web-access" data-web-access data-config="${esc(JSON.stringify(data))}"><div class="panel-heading"><h2>Webzugriff</h2><span class="pill">${esc(String(settings.mode||'https').toUpperCase())}</span></div><p>Aktuelle Adresse: <a href="${esc(data.origin)}">${esc(data.origin)}</a></p>${data.last_error?`<p class="notice warning" role="status">${esc(data.last_error)}</p>`:''}${data.demo?'<p class="hint">In der Demo werden keine Netzwerkports verändert.</p>':''}<form data-web-access-form><div class="web-access-fields"><label>Verbindung<select name="mode" ${disabled?'disabled':''}><option value="https" ${settings.mode==='https'?'selected':''}>HTTPS · verschlüsselt</option><option value="http" ${settings.mode==='http'?'selected':''}>HTTP</option></select></label><label>HTTP-Port<input name="http_port" type="number" inputmode="numeric" min="1" max="65535" required value="${esc(settings.http_port||80)}" ${disabled?'disabled':''}></label><label>HTTPS-Port<input name="https_port" type="number" inputmode="numeric" min="1" max="65535" required value="${esc(settings.https_port||443)}" ${disabled?'disabled':''}></label></div><p class="hint" data-web-redirect-note>${settings.mode==='https'?'HTTP wird automatisch auf HTTPS weitergeleitet. Aufgerufene Pfade bleiben erhalten.':'Die Weboberfläche wird über HTTP bereitgestellt.'}</p><div class="form-actions"><button class="button primary" type="submit" ${disabled?'disabled':''}>Webzugriff ändern</button><span class="hint" role="status" data-web-access-status></span></div></form><div data-web-pending ${pending?'':'hidden'}><p class="notice">Neue Adresse: <strong>${esc(data.origin)}</strong><br>Öffne diese Adresse und bestätige den Zugriff innerhalb von <span data-web-deadline></span>. Andernfalls wird die bisherige Einstellung wiederhergestellt.</p><div class="form-actions"><a class="button primary" href="${esc(data.origin)}/#settings?section=general" data-web-open>Neue Adresse öffnen</a><button class="button primary" type="button" data-web-confirm>Verbindung bestätigen</button><button class="button" type="button" data-web-cancel>Zurücknehmen</button></div></div><p class="hint">Zertifikat: ${esc(data.certificate?.label||'Automatisches lokales Titan-Zertifikat')}</p><p class="notice warning" role="alert" data-web-access-error hidden></p></section>`;
 }
 function dispose(){current?.();current=null;}
 function mount(scope,ctx){
  dispose();let panel=scope.querySelector('[data-web-access]');if(!panel)return;
  let data=JSON.parse(panel.dataset.config),alive=true,busy=false,polling=false;const listeners=[];
  const listen=(node,event,fn)=>{if(node){node.addEventListener(event,fn);listeners.push([node,event,fn]);}};
  const status=panel.querySelector('[data-web-access-status]'),error=panel.querySelector('[data-web-access-error]');
  const showError=failure=>{if(!alive)return;error.hidden=false;error.textContent=failure.message||String(failure);};
  function refreshPending(){
   const pending=!!data.pending;panel.querySelector('[data-web-pending]').hidden=!pending;
   const here=scope.ownerDocument.defaultView.location.origin===data.origin;
   panel.querySelector('[data-web-confirm]').hidden=!pending||!here;
   panel.querySelector('[data-web-confirm]').disabled=!!(busy||data.confirming);
   if(status)status.textContent=data.confirming?'Adresse wird aktiviert …':'';
   panel.querySelector('[data-web-open]').hidden=!pending||here;
   panel.querySelector('[data-web-open]').href=data.origin+'/#settings?section=general';
   for(const node of panel.querySelectorAll('form input,form select,form button'))node.disabled=!!(pending||data.demo||busy);
   if(pending)panel.querySelector('[data-web-deadline]').textContent=Math.max(0,Math.ceil(data.deadline-Date.now()/1000))+' Sekunden';
  }
  async function change(route,body){if(busy)return;busy=true;error.hidden=true;refreshPending();try{const value=await ctx.api(route,body);if(!alive)return;data=value;ctx.toast?.(data.pending?'Neue Webadresse vorbereitet. Bitte Zugriff bestätigen.':'Webzugriff gespeichert.');await ctx.refresh?.();}catch(failure){showError(failure);}finally{busy=false;if(alive)refreshPending();}}
  const form=panel.querySelector('[data-web-access-form]');
  listen(form,'submit',event=>{event.preventDefault();const input=new FormData(form);void change('/api/web-access',{settings:{mode:input.get('mode'),http_port:Number(input.get('http_port')),https_port:Number(input.get('https_port'))},expected_revision:data.revision});});
  listen(form.elements.mode,'change',()=>{panel.querySelector('[data-web-redirect-note]').textContent=form.elements.mode.value==='https'?'HTTP wird automatisch auf HTTPS weitergeleitet. Aufgerufene Pfade bleiben erhalten.':'Die Weboberfläche wird über HTTP bereitgestellt.';});
  listen(panel.querySelector('[data-web-confirm]'),'click',()=>void change('/api/web-access/confirm',{expected_revision:data.revision}));
  listen(panel.querySelector('[data-web-cancel]'),'click',()=>void change('/api/web-access/cancel',{}));
  const timer=setInterval(async()=>{if(!alive)return;refreshPending();if(!data.pending||polling||busy)return;polling=true;try{const next=await ctx.api('/api/web-access');if(!alive)return;if(!next.pending||next.revision!==data.revision){await ctx.refresh?.();return;}data=next;}catch(failure){if(alive&&status)status.textContent='Verbindung wird wiederhergestellt …';}finally{polling=false;}},2000);
  refreshPending();current=()=>{alive=false;clearInterval(timer);for(const[node,event,fn]of listeners)node.removeEventListener(event,fn);};return{dispose};
 }
 return{render,mount,dispose};
});
