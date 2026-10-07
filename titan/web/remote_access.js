'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object')module.exports=ui;if(root)root.TitanRemoteAccess=ui;})(typeof window==='undefined'?null:window,function(){
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let cleanup=null;
 function checks(diagnosis){return diagnosis?.checks?.length?`<div class="remote-checks" role="status">${diagnosis.checks.map(check=>`<p><strong>${check.ok===true?'✓':check.ok===false?'!':'—'} ${esc(check.name)}</strong><br>${esc(check.message)}</p>`).join('')}<small>Prüfung: ${esc(new Date(diagnosis.checked_at*1000).toLocaleString('de-DE'))}</small></div>`:'<p class="hint">Noch keine Verbindungsprüfung ausgeführt. Ein laufender Connector allein bestätigt den externen Zugang nicht.</p>';}
 function render(data){
  const remote=data.remote||{},disabled=data.demo?'disabled':'';
  return `<section class="panel remote-access" data-remote-access data-config="${esc(JSON.stringify(data))}"><div class="panel-heading"><h2>Fernzugriff · Cloudflare Tunnel</h2><span class="pill ${remote.enabled?'':'gray'}">${remote.enabled?'Aktiviert':'Deaktiviert'}</span></div><form data-remote-form><label class="checkbox-row"><input type="checkbox" name="enabled" ${remote.enabled?'checked':''} ${disabled}>Titan über eine öffentliche HTTPS-Adresse bereitstellen</label><div class="web-access-fields"><label>Öffentliche Titan-Adresse<input name="public_origin" type="url" placeholder="https://nas.example.de" value="${esc(remote.public_origin)}" ${disabled}></label><label>Tunnel-Connector<select name="connector" ${disabled}><option value="">Cloudflared im Host-Netz · selbst verwaltet</option>${(data.connectors||[]).map(row=>`<option value="${esc(row.id)}" ${row.id===remote.connector?'selected':''}>${esc(row.name)}</option>`).join('')}</select></label></div><p class="hint">Titan prüft das tatsächliche Netzwerk der gewählten App und beschränkt den lokalen Tunnel-Zugang darauf. Die lokale NAS-Adresse bleibt erhalten.</p>${remote.service_url?`<div class="notice"><strong>Service URL in Cloudflare</strong><p><code>${esc(remote.service_url)}</code></p><small>${remote.sources?.length?'Docker-Bridge: '+esc(remote.sources.join(', ')):'Host-Netz · nur auf dem NAS erreichbar'}. Den öffentlichen Hostnamen unverändert weiterreichen. Dieses interne HTTP-Ziel benötigt kein lokales TLS-Zertifikat.</small></div>`:''}<details><summary>Öffentliche App-Adressen (${Object.keys(remote.app_urls||{}).length})</summary><p class="hint">Trage die ausdrücklich eingerichtete HTTPS-Adresse einer App ein. Die zugehörige Route und gegebenenfalls die vertrauenswürdige Domain richtest du in Cloudflare und in der App ein.</p><div class="web-access-fields">${(data.apps||[]).map(row=>`<label>${esc(row.name)}<input type="url" data-remote-app="${esc(row.id)}" value="${esc(remote.app_urls?.[row.id]||'')}" placeholder="https://app.example.de" ${disabled}></label>`).join('')||'<p class="hint">Noch keine Apps installiert.</p>'}</div></details><div class="form-actions"><button class="button primary" type="submit" ${disabled}>Fernzugriff speichern</button><button class="button" type="button" data-remote-diagnose ${!remote.enabled||data.demo?'disabled':''}>Verbindung prüfen</button>${remote.enabled?`<a class="button" href="${esc(remote.public_origin)}" target="_blank" rel="noopener noreferrer">Öffentlichen Zugang öffnen ↗</a>`:''}</div></form><div data-remote-checks>${checks(data.diagnosis)}</div><p class="hint" role="status" data-remote-status></p><p class="notice warning" role="alert" data-remote-error hidden></p></section>`;
 }
 function dispose(){cleanup?.();cleanup=null;}
 function mount(scope,ctx){
  dispose();let panel=scope.querySelector('[data-remote-access]');if(!panel)return;
  let data=JSON.parse(panel.dataset.config),alive=true,busy=false;
  const query=selector=>panel.querySelector(selector);
  function replace(value){if(!alive)return;data=value;const holder=panel.parentElement;panel.outerHTML=render(value);panel=holder.querySelector('[data-remote-access]');}
  async function perform(diagnose){
   if(busy||data.demo)return;busy=true;query('[data-remote-error]').hidden=true;
   try{
    let body={};if(!diagnose){const form=query('[data-remote-form]');body={enabled:form.elements.enabled.checked,public_origin:form.elements.public_origin.value.trim(),connector:form.elements.connector.value,app_urls:{},expected_revision:data.revision};for(const input of panel.querySelectorAll('[data-remote-app]'))if(input.value.trim())body.app_urls[input.dataset.remoteApp]=input.value.trim();}
    query('[data-remote-status]').textContent=diagnose?'Connector, Netzwerk und öffentliche HTTPS-Adresse werden geprüft …':'Fernzugriff wird gespeichert …';
    for(const node of panel.querySelectorAll('button,input,select'))node.disabled=true;
    const value=await ctx.api(diagnose?'/api/remote-access/diagnose':'/api/remote-access',body);if(!alive)return;
    replace(diagnose?{...data,diagnosis:value}:value);ctx.toast?.(diagnose?value.message:'Fernzugriff gespeichert. Tunnel-Zieladresse in Cloudflare übernehmen.');
   }catch(error){if(alive){query('[data-remote-error]').hidden=false;query('[data-remote-error]').textContent=error.message;query('[data-remote-status]').textContent='';}}
   finally{busy=false;if(alive){for(const node of panel.querySelectorAll('button,input,select'))node.disabled=false;const button=query('[data-remote-diagnose]');if(button)button.disabled=!data.remote?.enabled;}}
  }
  const submit=event=>{if(event.target.matches?.('[data-remote-form]')){event.preventDefault();void perform(false);}};
  const click=event=>{if(event.target.closest?.('[data-remote-diagnose]')&&!event.target.disabled){event.preventDefault();void perform(true);}};
  scope.addEventListener('submit',submit);scope.addEventListener('click',click);cleanup=()=>{alive=false;scope.removeEventListener('submit',submit);scope.removeEventListener('click',click);};
 }
 return {render,checks,mount,dispose};
});
